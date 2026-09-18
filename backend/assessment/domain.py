"""Internal assessment models used by the legacy-compatible evaluation flow."""

from dataclasses import dataclass
import re
from typing import Any, Awaitable, Callable


ShortAnswerEvaluator = Callable[
    [str, str, str, str, list[str]], Awaitable[Any]
]


@dataclass(frozen=True)
class LegacyQuestion:
    question_id: str
    question_type: str
    prompt: str


@dataclass(frozen=True)
class LegacyAnswerKey:
    answer: Any = None
    explanation: str = ""
    reference_answer: str | None = None
    rubric: tuple[str, ...] = ()


@dataclass(frozen=True)
class LegacyActivity:
    activity_id: str
    objective: str
    content: str
    questions: tuple[LegacyQuestion, ...]
    answer_keys: dict[str, LegacyAnswerKey]


@dataclass(frozen=True)
class EvaluationItem:
    question_id: str
    correct: bool
    score: int
    feedback: str
    reference_answer: str | None
    misconception: str | None
    error_type: str | None = None
    confidence: float | None = None
    missing_rubric: tuple[str, ...] = ()
    follow_up_question: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "questionId": self.question_id,
            "correct": self.correct,
            "score": self.score,
            "feedback": self.feedback,
            "referenceAnswer": self.reference_answer,
            "misconception": self.misconception,
        }
        if self.error_type is not None:
            result["errorType"] = self.error_type
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.missing_rubric:
            # The public result contains stable IDs only; rubric text remains
            # in answer_key_json and is never copied here.
            candidate = str(self.missing_rubric[0])
            # Natural-language rubric labels are private.  Only stable IDs
            # produced by the spec (or legacy numeric indexes) are public.
            if re.fullmatch(r"(?:rubric[-_]\d+|\d+|[A-Za-z][A-Za-z0-9_.-]*)", candidate):
                result["missingRubricId"] = candidate.replace("rubric_", "rubric-")
        return result


@dataclass(frozen=True)
class AttemptEvaluation:
    items: tuple[EvaluationItem, ...]
    score: int
    mastery_level: str
    diagnostic_summary: str
    misconceptions: tuple[str, ...]
    follow_up: dict[str, Any] | None = None
    low_confidence: bool = False

    def result_dict(self) -> dict[str, Any]:
        result = {
            "items": [item.as_dict() for item in self.items],
            "misconceptions": list(self.misconceptions),
        }
        if self.follow_up:
            result["followUp"] = dict(self.follow_up)
        if self.low_confidence:
            result["lowConfidence"] = True
        return result


@dataclass(frozen=True)
class SubmissionResult:
    """The completed persistence result returned by the application service."""

    attempt: Any
    evaluation: AttemptEvaluation
