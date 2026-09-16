from ..ai.gateway import AIGateway
from .prompts import TEACHER_AGENT_SYSTEM
from .schemas import TeacherGuidanceDraft


class TeacherAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    async def create_section_intro(self, card_title: str, section_title: str, content: str) -> TeacherGuidanceDraft:
        return await self._create(
            f"知识卡：{card_title}\n章节：{section_title}\n课程内容：{content}",
            "section_enter",
        )

    async def create_side_followup(
        self, card_title: str, section_title: str, content: str, question: str, answer: str
    ) -> TeacherGuidanceDraft:
        return await self._create(
            f"知识卡：{card_title}\n章节：{section_title}\n课程内容：{content}\n"
            f"学生问题：{question}\n答疑助教回答：{answer}",
            "side_question",
        )

    async def create_activity_followup(
        self, card_title: str, section_title: str, objective: str, score: int, diagnostic: str
    ) -> TeacherGuidanceDraft:
        return await self._create(
            f"知识卡：{card_title}\n章节：{section_title}\n教学目标：{objective}\n"
            f"得分：{score}\n诊断：{diagnostic}",
            "activity_result",
        )

    async def _create(self, context: str, trigger: str) -> TeacherGuidanceDraft:
        result = await self.gateway.structured(
            [
                {"role": "system", "content": TEACHER_AGENT_SYSTEM},
                {"role": "user", "content": f"触发类型：{trigger}\n{context}"},
            ],
            task="teacher_guidance",
            schema=TeacherGuidanceDraft.model_json_schema(),
        )
        return TeacherGuidanceDraft.model_validate(result)
