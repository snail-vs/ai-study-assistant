"""Orchestrate evaluation and creation of a completed activity attempt."""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import Session

from ..models import ActivityAttempt, LearningActivity, now
from .domain import AttemptEvaluation, LegacyActivity, LegacyAnswerKey, SubmissionResult
from .evaluators import LegacyEvaluationOrchestrator


class AttemptSubmissionService:
    """Evaluate a legacy activity before making any database side effect."""

    def __init__(
        self,
        short_answer_evaluator_factory: Callable[[], Callable[..., Awaitable[Any]]] | None = None,
        *,
        short_answer_evaluator: Callable[..., Awaitable[Any]] | None = None,
    ):
        # The direct evaluator keyword remains useful for callers/tests, while
        # the factory is what keeps provider setup lazy in the API.
        if short_answer_evaluator_factory is None and short_answer_evaluator is not None:
            short_answer_evaluator_factory = lambda: short_answer_evaluator
        self.orchestrator = LegacyEvaluationOrchestrator(short_answer_evaluator_factory)

    async def evaluate(
        self, activity: LegacyActivity, answers: dict[str, Any]
    ) -> AttemptEvaluation:
        items = []
        for question in activity.questions:
            key = activity.answer_keys.get(question.question_id)
            if key is None:
                # Keep old behavior for a missing answer key: an unanswered
                # objective task is simply marked incorrect.
                key = LegacyAnswerKey()
            answer = answers.get(question.question_id)
            items.append(await self.orchestrator.evaluate(activity, question, answer, key))

        score = round(sum(item.score for item in items) / len(items)) if items else 0
        low_confidence = any(
            item.confidence is not None and item.confidence < 0.7
            for item in items
        )
        mastery = (
            "needs_review" if low_confidence else
            "mastered" if score >= 85 else "developing" if score >= 60 else "needs_review"
        )
        misconceptions = tuple(item.misconception for item in items if item.misconception)
        diagnostic = (
            "本节核心目标掌握较好，可以继续下一节。" if mastery == "mastered" else
            "已经掌握主要内容，但建议回看错误题目后再继续。" if mastery == "developing" else
            "本节核心概念还不稳定，建议先回看课程内容和导师引导。"
        )
        follow_up = self._select_follow_up(activity, items)
        return AttemptEvaluation(
            items=tuple(items),
            score=score,
            mastery_level=mastery,
            diagnostic_summary=diagnostic,
            misconceptions=misconceptions,
            follow_up=follow_up,
            low_confidence=low_confidence,
        )

    @staticmethod
    def _select_follow_up(activity: LegacyActivity, items: list[Any]) -> dict[str, Any] | None:
        """Select exactly one actionable, high-confidence AI suggestion.

        Provider output is advisory: the server requires all fields and maps a
        missing rubric back to an index in the private answer key before it is
        persisted.  Rubric text is never included in the returned structure.
        """
        for item, question in zip(items, activity.questions):
            if question.question_type != "short_answer":
                continue
            if item.confidence is None or item.confidence < 0.7:
                continue
            if item.score >= 100 or not item.missing_rubric or not item.follow_up_question:
                continue
            key = activity.answer_keys.get(question.question_id, LegacyAnswerKey())
            missing = item.missing_rubric[0]
            rubric_index: int | None = None
            if str(missing).isdigit():
                index = int(missing)
                if 0 <= index < len(key.rubric):
                    rubric_index = index
            if rubric_index is None:
                for index, rubric in enumerate(key.rubric):
                    if missing == rubric or missing == f"rubric-{index}" or missing == f"rubric_{index}":
                        rubric_index = index
                        break
            if rubric_index is None:
                continue
            return {
                "id": f"follow-up-{question.question_id}-1",
                "parentTaskId": question.question_id,
                "prompt": item.follow_up_question,
                "status": "pending",
                "privateParentQuestionId": question.question_id,
                "privateRubricIndex": rubric_index,
            }
        return None

    def build_attempt(
        self,
        activity: LearningActivity,
        answers: dict[str, Any],
        evaluation: AttemptEvaluation,
    ) -> ActivityAttempt:
        """Build an ORM object only after evaluation has fully succeeded."""
        return ActivityAttempt(
            activity_id=activity.id,
            status="follow_up_pending" if evaluation.follow_up else "evaluated",
            answers_json=json.dumps(answers, ensure_ascii=False),
            result_json=json.dumps(evaluation.result_dict(), ensure_ascii=False),
            score=evaluation.score,
            mastery_level=evaluation.mastery_level,
            diagnostic_summary=evaluation.diagnostic_summary,
            completed_at=None if evaluation.follow_up else now(),
        )

    async def evaluate_follow_up(
        self,
        activity: LegacyActivity,
        follow_up: dict[str, Any],
        answer: Any,
        evaluator: Callable[..., Awaitable[Any]],
    ) -> Any:
        parent_id = follow_up.get("privateParentQuestionId") or follow_up.get("parentTaskId")
        question = next((item for item in activity.questions if item.question_id == parent_id), None)
        if question is None:
            raise ValueError("follow-up parent task not found")
        key = activity.answer_keys.get(parent_id, LegacyAnswerKey())
        index = follow_up.get("privateRubricIndex")
        rubric = [key.rubric[index]] if isinstance(index, int) and 0 <= index < len(key.rubric) else []
        return await evaluator(
            activity.objective,
            activity.content,
            follow_up["prompt"],
            str(answer or ""),
            rubric,
        )

    def persist(self, db: Session, attempt: ActivityAttempt) -> ActivityAttempt:
        db.add(attempt)
        db.commit()
        db.refresh(attempt)
        return attempt

    async def submit(
        self,
        db: Session,
        model_activity: LearningActivity,
        activity: LegacyActivity,
        answers: dict[str, Any],
    ) -> SubmissionResult:
        """Evaluate and persist only after every evaluator has succeeded."""
        evaluation = await self.evaluate(activity, answers)
        attempt = self.build_attempt(model_activity, answers, evaluation)
        self.persist(db, attempt)
        return SubmissionResult(attempt=attempt, evaluation=evaluation)
