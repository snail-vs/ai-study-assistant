import json
import logging

from .language_policy import infer_response_language, response_language_instruction
from .prompts import (
    CONTENT_AUTHOR_SYSTEM,
    CONTENT_REPAIR_SYSTEM,
    CONTENT_REVIEWER_SYSTEM,
    COURSE_PLANNER_SYSTEM,
    SECTION_SUMMARY_SYSTEM,
)
from .schemas import (
    ActualSectionSummary,
    CardSectionDraft,
    KnowledgeCardDraft,
    KnowledgeCardPlanDraft,
    SectionContentDraft,
    SectionGenerationContext,
    SectionPlanDigest,
    SectionPlanDraft,
    SectionQualityReport,
    SectionQualityReview,
)
from ..ai.gateway import AIGateway


logger = logging.getLogger("studycenter.ai.main_agent")

_SCALE_CONSTRAINTS = {
    "quick": (2, 3, "300～500"),
    "standard": (5, 8, "500～900"),
    "series": (8, 12, "350～700"),
}


def _model_or_dict(value):
    return value.model_dump(by_alias=True) if hasattr(value, "model_dump") else value


def _outline_section(item: dict) -> SectionPlanDraft:
    return SectionPlanDraft(
        title=str(item.get("title", "")).strip(),
        teaching_objective=str(
            item.get("objective") or item.get("teaching_objective") or item.get("teachingObjective") or ""
        ).strip(),
        content_type=item.get("role") or item.get("content_type") or item.get("contentType") or "concept",
        prerequisites=item.get("prerequisites") or [],
        key_concepts=item.get("keyConcepts") or item.get("key_concepts") or [],
        misconceptions=item.get("misconceptions") or [],
        teaching_strategy=str(item.get("teachingStrategy") or item.get("teaching_strategy") or ""),
        practice_task=item.get("practiceTask") or item.get("practice_task"),
        mastery_evidence=str(item.get("masteryEvidence") or item.get("mastery_evidence") or ""),
        previous_connection=str(item.get("previousConnection") or item.get("previous_connection") or ""),
        next_connection=str(item.get("nextConnection") or item.get("next_connection") or ""),
        estimated_minutes=item.get("estimatedMinutes") or item.get("estimated_minutes"),
    )


class MainAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    async def plan_course(
        self,
        goal: str,
        brief: dict | None = None,
        scale: str = "standard",
        approved_outline: list[dict] | None = None,
    ) -> KnowledgeCardPlanDraft:
        brief = _model_or_dict(brief) or {}
        approved_outline = [_model_or_dict(item) for item in (approved_outline or [])]
        minimum, maximum, target_length = _SCALE_CONSTRAINTS.get(
            scale, _SCALE_CONSTRAINTS["standard"]
        )

        if approved_outline:
            topic = str(brief.get("topic") or goal).strip()
            summary = str(
                brief.get("learningOutcome")
                or brief.get("learningGoalDetails")
                or goal
            ).strip()
            return KnowledgeCardPlanDraft(
                title=topic,
                summary=summary,
                sections=[_outline_section(item) for item in approved_outline],
            )

        language = infer_response_language(brief.get("topic") or goal)
        planner_system = (
            COURSE_PLANNER_SYSTEM
            + "\n"
            + response_language_instruction(language)
            + f"\n本次规模为 {scale}：章节数应为 {minimum}～{maximum} 节，每节正文约 {target_length} 字。series 只生成系列总览型主卡。"
        )
        planner_request = json.dumps(
            {
                "responseLanguage": language,
                "learningGoal": goal,
                "learnerBrief": brief,
            },
            ensure_ascii=False,
        )
        plan_result = await self.gateway.structured(
            [
                {"role": "system", "content": planner_system},
                {"role": "user", "content": planner_request},
            ],
            task="course_plan",
            schema=KnowledgeCardPlanDraft.model_json_schema(),
        )
        validation_error: ValueError | None = None
        try:
            plan = KnowledgeCardPlanDraft.model_validate(plan_result)
            if len(plan.sections) < minimum:
                validation_error = ValueError(
                    f"模型只返回 {len(plan.sections)} 节，建议至少 {minimum} 节"
                )
        except ValueError as exc:
            validation_error = exc
            plan = None

        if validation_error is not None:
            repaired = await self.gateway.structured(
                [
                    {
                        "role": "system",
                        "content": (
                            planner_system
                            + "\n这是一次课程规划结构修复。必须只返回完整 JSON，且必须包含非空 title、summary 和 sections；"
                            "sections 必须是具体章节对象数组，禁止用通用章节凑数。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "task": "repair_course_plan",
                                "originalRequest": planner_request,
                                "originalResponse": plan_result,
                                "validationError": str(validation_error),
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
                raise ValueError(
                    f"模型修复后仍未生成有效课程规划：{repair_exc}"
                ) from repair_exc
            if len(plan.sections) < minimum:
                plan.warnings.append(
                    f"规划仅包含 {len(plan.sections)} 节，少于建议的 {minimum} 节；已保留有效规划而未追加通用章节。"
                )

        if len(plan.sections) > maximum:
            plan.sections = plan.sections[:maximum]
            plan.warnings.append(f"规划超过 {maximum} 节，已按课程规模截断。")
        return plan

    @staticmethod
    def build_section_context(
        plan: KnowledgeCardPlanDraft,
        brief: dict,
        section_index: int,
        actual_summaries: list[ActualSectionSummary],
    ) -> SectionGenerationContext:
        digests = [
            SectionPlanDigest(
                title=section.title,
                teaching_objective=section.teaching_objective,
                content_type=section.content_type,
                key_concepts=section.key_concepts,
            )
            for section in plan.sections
        ]
        taught_concepts = list(dict.fromkeys(
            concept for summary in actual_summaries for concept in summary.actually_taught
        ))
        introduced_not_mastered = list(dict.fromkeys(
            concept for summary in actual_summaries for concept in summary.introduced_not_mastered
        ))
        examples_already_used = list(dict.fromkeys(
            example for summary in actual_summaries for example in summary.examples_used
        ))
        return SectionGenerationContext(
            learner_brief=brief,
            course_title=plan.title,
            course_summary=plan.summary,
            course_plan=digests,
            current_section=plan.sections[section_index],
            previous_actual_summary=actual_summaries[-1] if actual_summaries else None,
            taught_concepts=taught_concepts,
            introduced_not_mastered=introduced_not_mastered,
            examples_already_used=examples_already_used,
            next_section=digests[section_index + 1] if section_index + 1 < len(digests) else None,
        )

    async def _review_section(
        self,
        context: SectionGenerationContext,
        content: SectionContentDraft,
        language: str,
    ) -> SectionQualityReview:
        result = await self.gateway.structured(
            [
                {"role": "system", "content": CONTENT_REVIEWER_SYSTEM + "\n" + response_language_instruction(language)},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "responseLanguage": language,
                            "sectionContext": context.model_dump(),
                            "contentMarkdown": content.content_markdown,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            task="section_review",
            schema=SectionQualityReview.model_json_schema(),
        )
        return SectionQualityReview.model_validate(result)

    async def generate_section(
        self,
        context: SectionGenerationContext,
        *,
        scale: str,
        language: str,
    ) -> CardSectionDraft:
        target_length = _SCALE_CONSTRAINTS.get(scale, _SCALE_CONSTRAINTS["standard"])[2]
        author_payload = {
            "responseLanguage": language,
            "targetLength": target_length,
            "sectionContext": context.model_dump(),
        }
        content_result = await self.gateway.structured(
            [
                {"role": "system", "content": CONTENT_AUTHOR_SYSTEM + "\n" + response_language_instruction(language)},
                {"role": "user", "content": json.dumps(author_payload, ensure_ascii=False)},
            ],
            task="section_content",
            schema=SectionContentDraft.model_json_schema(),
        )
        content = SectionContentDraft.model_validate(content_result)
        review = await self._review_section(context, content, language)
        final_review = review
        revision_attempted = False

        if review.needs_revision:
            revision_attempted = True
            repaired_result = await self.gateway.structured(
                [
                    {"role": "system", "content": CONTENT_REPAIR_SYSTEM + "\n" + response_language_instruction(language)},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "responseLanguage": language,
                                "sectionContext": context.model_dump(),
                                "originalContentMarkdown": content.content_markdown,
                                "blockingIssues": review.blocking_issues,
                                "repairInstructions": review.repair_instructions,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                task="section_repair",
                schema=SectionContentDraft.model_json_schema(),
            )
            content = SectionContentDraft.model_validate(repaired_result)
            final_review = await self._review_section(context, content, language)

        summary_result = await self.gateway.structured(
            [
                {"role": "system", "content": SECTION_SUMMARY_SYSTEM + "\n" + response_language_instruction(language)},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "responseLanguage": language,
                            "sectionContext": context.model_dump(),
                            "finalContentMarkdown": content.content_markdown,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            task="section_summary",
            schema=ActualSectionSummary.model_json_schema(),
        )
        actual_summary = ActualSectionSummary.model_validate(summary_result)
        quality_report = SectionQualityReport(
            initial_review=review,
            final_review=final_review,
            revision_attempted=revision_attempted,
            quality_status="passed" if not final_review.needs_revision else "needs_attention",
        )
        scores = {
            field: getattr(final_review, field)
            for field in (
                "correctness", "goal_alignment", "clarity", "information_density",
                "prerequisite_fit", "cognitive_load", "example_quality",
                "active_learning", "personalization",
            )
        }
        logger.info(
            "section generated: card=%s section=%s scores=%s needs_revision=%s",
            context.course_title,
            context.current_section.title,
            scores,
            final_review.needs_revision,
        )
        return CardSectionDraft(
            title=context.current_section.title,
            content_markdown=content.content_markdown,
            content_type=context.current_section.content_type,
            teaching_objective=context.current_section.teaching_objective,
            quality_report=quality_report.model_dump(),
            plan=context.current_section.model_dump(),
            actual_summary=actual_summary.model_dump(),
        )

    async def create_card(
        self,
        goal: str,
        brief: dict | None = None,
        scale: str = "standard",
        approved_outline: list[dict] | None = None,
    ) -> KnowledgeCardDraft:
        normalized_brief = _model_or_dict(brief) or {}
        plan = await self.plan_course(goal, normalized_brief, scale, approved_outline)
        language = infer_response_language(normalized_brief.get("topic") or goal)
        sections: list[CardSectionDraft] = []
        actual_summaries: list[ActualSectionSummary] = []
        for index in range(len(plan.sections)):
            context = self.build_section_context(plan, normalized_brief, index, actual_summaries)
            section = await self.generate_section(context, scale=scale, language=language)
            sections.append(section)
            actual_summaries.append(ActualSectionSummary.model_validate(section.actual_summary))
        return KnowledgeCardDraft(title=plan.title, summary=plan.summary, sections=sections)
