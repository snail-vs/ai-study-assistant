import json
import logging

from .prompts import (
    CONTENT_AUTHOR_SYSTEM,
    CONTENT_REPAIR_SYSTEM,
    CONTENT_REVIEWER_SYSTEM,
    COURSE_PLANNER_SYSTEM,
)
from .schemas import (
    CardSectionDraft,
    KnowledgeCardDraft,
    KnowledgeCardPlanDraft,
    SectionContentDraft,
    SectionQualityReport,
    SectionQualityReview,
)
from ..ai.gateway import AIGateway


logger = logging.getLogger("studycenter.ai.main_agent")


class MainAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    async def create_card(self, goal: str) -> KnowledgeCardDraft:
        plan_result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_PLANNER_SYSTEM},
                {"role": "user", "content": goal},
            ],
            task="course_plan",
            schema=KnowledgeCardPlanDraft.model_json_schema(),
        )
        plan = KnowledgeCardPlanDraft.model_validate(plan_result)
        sections: list[CardSectionDraft] = []
        for index, section in enumerate(plan.sections):
            content_result = await self.gateway.structured(
                [
                    {"role": "system", "content": CONTENT_AUTHOR_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"学习目标：{goal}\n知识卡：{plan.title}\n知识卡摘要：{plan.summary}\n"
                            f"章节序号：{index + 1}/{len(plan.sections)}\n章节标题：{section.title}\n"
                            f"教学目标：{section.teaching_objective}\n内容类型：{section.content_type}"
                        ),
                    },
                ],
                task="section_content",
                schema=SectionContentDraft.model_json_schema(),
            )
            content = SectionContentDraft.model_validate(content_result)
            review_result = await self.gateway.structured(
                [
                    {"role": "system", "content": CONTENT_REVIEWER_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"学习目标：{goal}\n知识卡：{plan.title}\n章节标题：{section.title}\n"
                            f"本节教学目标：{section.teaching_objective}\n内容类型：{section.content_type}\n\n"
                            f"待审查正文：\n{content.content_markdown}"
                        ),
                    },
                ],
                task="section_review",
                schema=SectionQualityReview.model_json_schema(),
            )
            review = SectionQualityReview.model_validate(review_result)
            logger.info(
                "section quality review: card=%s section=%s scores=%s needs_revision=%s",
                plan.title,
                section.title,
                {
                    "correctness": review.correctness,
                    "goal_alignment": review.goal_alignment,
                    "clarity": review.clarity,
                    "information_density": review.information_density,
                },
                review.needs_revision,
            )
            final_review = review
            revision_attempted = False
            if review.needs_revision:
                revision_attempted = True
                logger.info(
                    "section quality repair: card=%s section=%s scores=%s blocking=%s",
                    plan.title,
                    section.title,
                    {
                        "correctness": review.correctness,
                        "goal_alignment": review.goal_alignment,
                        "clarity": review.clarity,
                        "information_density": review.information_density,
                    },
                    review.blocking_issues,
                )
                repaired_result = await self.gateway.structured(
                    [
                        {"role": "system", "content": CONTENT_REPAIR_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"章节标题：{section.title}\n教学目标：{section.teaching_objective}\n"
                                f"原正文：\n{content.content_markdown}\n\n"
                                f"阻断问题：{json.dumps(review.blocking_issues, ensure_ascii=False)}\n"
                                f"修订指令：{json.dumps(review.repair_instructions, ensure_ascii=False)}"
                            ),
                        },
                    ],
                    task="section_repair",
                    schema=SectionContentDraft.model_json_schema(),
                )
                content = SectionContentDraft.model_validate(repaired_result)
                final_review_result = await self.gateway.structured(
                    [
                        {"role": "system", "content": CONTENT_REVIEWER_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"学习目标：{goal}\n知识卡：{plan.title}\n章节标题：{section.title}\n"
                                f"本节教学目标：{section.teaching_objective}\n内容类型：{section.content_type}\n\n"
                                f"待审查正文：\n{content.content_markdown}"
                            ),
                        },
                    ],
                    task="section_review",
                    schema=SectionQualityReview.model_json_schema(),
                )
                final_review = SectionQualityReview.model_validate(final_review_result)
                logger.info(
                    "section quality re-review: card=%s section=%s scores=%s needs_revision=%s",
                    plan.title,
                    section.title,
                    {
                        "correctness": final_review.correctness,
                        "goal_alignment": final_review.goal_alignment,
                        "clarity": final_review.clarity,
                        "information_density": final_review.information_density,
                    },
                    final_review.needs_revision,
                )
            quality_report = SectionQualityReport(
                initial_review=review,
                final_review=final_review,
                revision_attempted=revision_attempted,
                quality_status="passed" if not final_review.needs_revision else "needs_attention",
            )
            sections.append(CardSectionDraft(
                title=section.title,
                content_markdown=content.content_markdown,
                content_type=section.content_type,
                teaching_objective=section.teaching_objective,
                quality_report=quality_report.model_dump(),
            ))
        return KnowledgeCardDraft(title=plan.title, summary=plan.summary, sections=sections)
