from .prompts import CONTENT_AUTHOR_SYSTEM, COURSE_PLANNER_SYSTEM
from .schemas import CardSectionDraft, KnowledgeCardDraft, KnowledgeCardPlanDraft, SectionContentDraft
from ..ai.gateway import AIGateway


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
            sections.append(CardSectionDraft(
                title=section.title,
                content_markdown=content.content_markdown,
                content_type=section.content_type,
                teaching_objective=section.teaching_objective,
            ))
        return KnowledgeCardDraft(title=plan.title, summary=plan.summary, sections=sections)
