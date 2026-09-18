"""Adapter for the current content_json/answer_key_json quiz format."""

from typing import Any

from .domain import LegacyActivity, LegacyAnswerKey, LegacyQuestion


class LegacyQuizAdapter:
    """Translate persisted v1 quiz JSON into the internal assessment model."""

    @staticmethod
    def from_json(
        activity_id: str,
        objective: str | None,
        section_content: str,
        content: dict[str, Any],
        answer_key: dict[str, Any],
    ) -> LegacyActivity:
        questions = tuple(
            LegacyQuestion(
                question_id=str(question.get("id")),
                question_type=str(question.get("type", "")),
                prompt=str(question.get("prompt", "")),
            )
            for question in content.get("questions", [])
        )
        keys = {
            str(question_id): LegacyAnswerKey(
                answer=value.get("answer"),
                explanation=str(value.get("explanation", "")),
                reference_answer=value.get("reference_answer"),
                rubric=tuple(str(item) for item in value.get("rubric", [])),
            )
            for question_id, value in answer_key.items()
            if isinstance(value, dict)
        }
        return LegacyActivity(
            activity_id=activity_id,
            objective=objective or "",
            content=section_content,
            questions=questions,
            answer_keys=keys,
        )
