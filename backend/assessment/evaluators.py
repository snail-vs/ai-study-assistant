"""Evaluators for the currently supported legacy quiz task kinds."""

from collections.abc import Awaitable, Callable
from typing import Any

from .domain import EvaluationItem, LegacyActivity, LegacyAnswerKey, LegacyQuestion


class LegacyEvaluationOrchestrator:
    """Dispatch legacy questions without coupling the service to task kinds."""

    def __init__(
        self,
        short_answer_evaluator_factory: Callable[[], Callable[..., Awaitable[Any]]] | None = None,
    ) -> None:
        self.short_answer_evaluator_factory = short_answer_evaluator_factory

    async def evaluate(
        self,
        activity: LegacyActivity,
        question: LegacyQuestion,
        answer: Any,
        key: LegacyAnswerKey,
    ) -> EvaluationItem:
        if question.question_type != "short_answer":
            return evaluate_deterministic(question, answer, key)
        if self.short_answer_evaluator_factory is None:
            raise RuntimeError("short-answer evaluator is not configured")
        evaluator = self.short_answer_evaluator_factory()
        evaluation = await evaluator(
            activity.objective,
            activity.content,
            question.prompt,
            str(answer or ""),
            list(key.rubric),
        )
        return evaluation_item_from_short_answer(question, key, evaluation)


def evaluate_deterministic(
    question: LegacyQuestion, answer: Any, key: LegacyAnswerKey
) -> EvaluationItem:
    correct = answer == key.answer
    return EvaluationItem(
        question_id=question.question_id,
        correct=correct,
        score=100 if correct else 0,
        feedback=key.explanation if correct else f"参考理解：{key.explanation}",
        reference_answer=None,
        misconception=None if correct else "需要重新检查本题对应的核心概念。",
    )


def evaluation_item_from_short_answer(
    question: LegacyQuestion, key: LegacyAnswerKey, evaluation: Any
) -> EvaluationItem:
    score = int(evaluation.score)
    return EvaluationItem(
        question_id=question.question_id,
        correct=score >= 60,
        score=score,
        feedback=evaluation.feedback,
        reference_answer=key.reference_answer,
        misconception=evaluation.misconception,
        error_type=getattr(evaluation, "error_type", None),
        confidence=getattr(evaluation, "confidence", None),
        missing_rubric=tuple(getattr(evaluation, "missing_rubric", ()) or ()),
        follow_up_question=getattr(evaluation, "follow_up_question", None),
    )
