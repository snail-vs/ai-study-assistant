from ..ai.gateway import AIGateway
from .prompts import ASSESSMENT_EVALUATOR_SYSTEM, ASSESSMENT_GENERATOR_SYSTEM
from .schemas import QuizDraft, ShortAnswerEvaluation


class AssessmentAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    async def generate_quiz(self, card_title: str, section_title: str, objective: str, content: str) -> QuizDraft:
        result = await self.gateway.structured(
            [
                {"role": "system", "content": ASSESSMENT_GENERATOR_SYSTEM},
                {"role": "user", "content": (
                    f"知识卡：{card_title}\n章节：{section_title}\n教学目标：{objective}\n"
                    f"章节内容：{content[:10000]}"
                )},
            ],
            task="quiz_generation",
            schema=QuizDraft.model_json_schema(),
        )
        return QuizDraft.model_validate(result)

    async def evaluate_short_answer(
        self, objective: str, content: str, question: str, answer: str, rubric: list[str]
    ) -> ShortAnswerEvaluation:
        result = await self.gateway.structured(
            [
                {"role": "system", "content": ASSESSMENT_EVALUATOR_SYSTEM},
                {"role": "user", "content": (
                    f"教学目标：{objective}\n章节内容：{content[:6000]}\n问题：{question}\n"
                    f"用户回答：{answer}\n评分依据：{'；'.join(rubric)}"
                )},
            ],
            task="quiz_evaluation",
            schema=ShortAnswerEvaluation.model_json_schema(),
        )
        return ShortAnswerEvaluation.model_validate(result)
