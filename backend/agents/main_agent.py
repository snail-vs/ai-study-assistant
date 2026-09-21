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
    SectionPlanDraft,
    SectionQualityReport,
    SectionQualityReview,
)
from .language_policy import infer_response_language, response_language_instruction
from ..ai.gateway import AIGateway


logger = logging.getLogger("studycenter.ai.main_agent")


class MainAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    async def create_card(
        self,
        goal: str,
        brief: dict | None = None,
        scale: str = "standard",
        approved_outline: list[dict] | None = None,
    ) -> KnowledgeCardDraft:
        constraints = {"quick": (2, 3, "300～500"), "standard": (5, 8, "500～900"), "series": (8, 12, "350～700")}.get(scale, (5, 8, "500～900"))
        brief_text = json.dumps(brief or {}, ensure_ascii=False)
        language = infer_response_language((brief or {}).get("topic") or goal)
        planner_system = (
            COURSE_PLANNER_SYSTEM
            + "\n"
            + response_language_instruction(language)
            + f"\n本次规模为 {scale}：章节数必须为 {constraints[0]}～{constraints[1]} 节，每节正文约 {constraints[2]} 字。series 只生成系列总览型主卡。"
        )
        planner_request = (
            f"responseLanguage={language}\n学习目标：{goal}\n结构化需求：{brief_text}"
        )
        plan_result = await self.gateway.structured(
            [
                {"role": "system", "content": planner_system},
                {"role": "user", "content": planner_request},
            ],
            task="course_plan",
            schema=KnowledgeCardPlanDraft.model_json_schema(),
        )
        try:
            plan = KnowledgeCardPlanDraft.model_validate(plan_result)
        except ValueError as exc:
            repaired = await self.gateway.structured(
                [
                    {
                        "role": "system",
                        "content": (
                            planner_system
                            + "\n这是一次课程规划结构修复。必须只返回完整 JSON，且必须包含非空 title、summary 和 sections；"
                            "sections 必须是章节对象数组，每项都必须包含 title、teaching_objective 和 content_type。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "task": "repair_course_plan",
                                "originalRequest": planner_request,
                                "originalResponse": plan_result,
                                "validationError": str(exc),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                task="course_plan",
                schema=KnowledgeCardPlanDraft.model_json_schema(),
            )
            try:
                plan = KnowledgeCardPlanDraft.model_validate(repaired)
            except ValueError as repair_exc:
                raise ValueError(f"模型修复后仍未生成有效课程规划：{repair_exc}") from repair_exc
        if approved_outline:
            plan.sections = [
                SectionPlanDraft(
                    title=str(item.get("title", "")).strip(),
                    teaching_objective=str(item.get("objective", "")).strip(),
                    content_type="concept",
                )
                for item in approved_outline
            ]
        if len(plan.sections) > constraints[1]:
            plan.sections = plan.sections[:constraints[1]]
        filler_titles = (
            ["Core concept review", "Hands-on case", "Common pitfalls and boundaries", "Integrated application", "Learning path review"]
            if language == "en"
            else ["核心概念回顾", "典型案例演练", "常见误区与边界", "综合应用任务", "学习路径总结"]
        )
        while len(plan.sections) < constraints[0]:
            index = len(plan.sections)
            title = filler_titles[index % len(filler_titles)]
            focus = (brief or {}).get("focus") or []
            if language == "en":
                objective = f"Reinforce the course objective through {focus[index % len(focus)]}" if focus else "Reinforce the core course objective through a transfer exercise"
            else:
                objective = f"围绕 {focus[index % len(focus)]} 巩固本课程的核心目标" if focus else "巩固本课程的核心目标并完成一次迁移练习"
            plan.sections.append(SectionPlanDraft(title=title, teaching_objective=objective, content_type="practice"))
        sections: list[CardSectionDraft] = []
        for index, section in enumerate(plan.sections):
            content_result = await self.gateway.structured(
                [
                    {"role": "system", "content": CONTENT_AUTHOR_SYSTEM + "\n" + response_language_instruction(language)},
                    {
                        "role": "user",
                        "content": (
                            f"responseLanguage={language}\n学习目标：{goal}\n知识卡：{plan.title}\n知识卡摘要：{plan.summary}\n"
                            f"章节序号：{index + 1}/{len(plan.sections)}\n章节标题：{section.title}\n"
                            f"教学目标：{section.teaching_objective}\n内容类型：{section.content_type}\n规模：{scale}，正文长度约 {constraints[2]} 字"
                        ),
                    },
                ],
                task="section_content",
                schema=SectionContentDraft.model_json_schema(),
            )
            content = SectionContentDraft.model_validate(content_result)
            review_result = await self.gateway.structured(
                [
                    {"role": "system", "content": CONTENT_REVIEWER_SYSTEM + "\n" + response_language_instruction(language)},
                    {
                        "role": "user",
                        "content": (
                            f"responseLanguage={language}\n学习目标：{goal}\n知识卡：{plan.title}\n章节标题：{section.title}\n"
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
                        {"role": "system", "content": CONTENT_REPAIR_SYSTEM + "\n" + response_language_instruction(language)},
                        {
                            "role": "user",
                            "content": (
                                f"responseLanguage={language}\n章节标题：{section.title}\n教学目标：{section.teaching_objective}\n"
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
                        {"role": "system", "content": CONTENT_REVIEWER_SYSTEM + "\n" + response_language_instruction(language)},
                        {
                            "role": "user",
                            "content": (
                                f"responseLanguage={language}\n学习目标：{goal}\n知识卡：{plan.title}\n章节标题：{section.title}\n"
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
