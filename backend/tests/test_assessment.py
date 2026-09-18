import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.assessment import AttemptSubmissionService, LegacyQuizAdapter


class Evaluation:
    def __init__(self, score=60, feedback="反馈", misconception=None):
        self.score = score
        self.feedback = feedback
        self.misconception = misconception


def legacy(content, keys):
    return LegacyQuizAdapter.from_json("activity-1", "目标", "章节内容", content, keys)


class AssessmentServiceTests(unittest.TestCase):
    def test_legacy_adapter_maps_questions_and_private_keys(self):
        activity = legacy(
            {"questions": [{"id": "q1", "type": "single_choice", "prompt": "选择"}]},
            {"q1": {"answer": "a", "explanation": "说明"}},
        )
        self.assertEqual(activity.questions[0].question_id, "q1")
        self.assertEqual(activity.answer_keys["q1"].answer, "a")
        self.assertEqual(activity.answer_keys["q1"].explanation, "说明")

    def test_objective_questions_do_not_call_ai(self):
        evaluator = AsyncMock(side_effect=AssertionError("AI must not be called"))
        activity = legacy(
            {"questions": [{"id": "q1", "type": "true_false", "prompt": "判断"}]},
            {"q1": {"answer": True, "explanation": "正确解释"}},
        )
        result = asyncio.run(AttemptSubmissionService(short_answer_evaluator=evaluator).evaluate(activity, {"q1": True}))
        self.assertEqual(result.score, 100)
        evaluator.assert_not_awaited()

        wrong = asyncio.run(AttemptSubmissionService(short_answer_evaluator=evaluator).evaluate(activity, {"q1": False}))
        self.assertEqual(wrong.items[0].feedback, "参考理解：正确解释")
        self.assertFalse(wrong.items[0].correct)

    def test_mixed_questions_and_mastery_boundaries(self):
        evaluator = AsyncMock(return_value=Evaluation(60, "简答反馈", "遗漏因果"))
        activity = legacy(
            {"questions": [
                {"id": "q1", "type": "single_choice", "prompt": "选择"},
                {"id": "q2", "type": "short_answer", "prompt": "解释"},
            ]},
            {"q1": {"answer": "a", "explanation": "选择解释"}, "q2": {"rubric": ["因果"]}},
        )
        result = asyncio.run(AttemptSubmissionService(short_answer_evaluator=evaluator).evaluate(activity, {"q1": "a", "q2": "回答"}))
        self.assertEqual(result.score, 80)
        self.assertEqual(result.mastery_level, "developing")
        self.assertEqual(result.misconceptions, ("遗漏因果",))

        for score, expected in ((85, "mastered"), (60, "developing"), (59, "needs_review")):
            boundary = legacy(
                {"questions": [{"id": "q1", "type": "short_answer", "prompt": "解释"}]},
                {"q1": {"rubric": []}},
            )
            current = AsyncMock(return_value=Evaluation(score))
            checked = asyncio.run(AttemptSubmissionService(short_answer_evaluator=current).evaluate(boundary, {"q1": "回答"}))
            self.assertEqual(checked.mastery_level, expected)

    def test_empty_quiz_scores_zero(self):
        activity = legacy({"questions": []}, {})
        result = asyncio.run(AttemptSubmissionService().evaluate(activity, {}))
        self.assertEqual(result.score, 0)
        self.assertEqual(result.mastery_level, "needs_review")

    def test_short_answer_failure_happens_before_attempt_build(self):
        evaluator = AsyncMock(side_effect=RuntimeError("provider failed"))
        activity = legacy(
            {"questions": [{"id": "q1", "type": "short_answer", "prompt": "解释"}]},
            {"q1": {"rubric": ["要点"]}},
        )
        with self.assertRaises(RuntimeError):
            asyncio.run(AttemptSubmissionService(short_answer_evaluator=evaluator).evaluate(activity, {"q1": "回答"}))

    def test_submit_does_not_touch_session_when_evaluator_fails(self):
        evaluator = AsyncMock(side_effect=RuntimeError("provider failed"))
        activity = legacy(
            {"questions": [{"id": "q1", "type": "short_answer", "prompt": "解释"}]},
            {"q1": {"rubric": ["要点"]}},
        )
        model_activity = MagicMock(id="activity-1")
        db = MagicMock()
        with self.assertRaises(RuntimeError):
            asyncio.run(AttemptSubmissionService(short_answer_evaluator=evaluator).submit(
                db, model_activity, activity, {"q1": "回答"}
            ))
        db.add.assert_not_called()
        db.commit.assert_not_called()
        db.refresh.assert_not_called()

    def test_objective_only_path_never_creates_short_answer_evaluator(self):
        factory = MagicMock(side_effect=AssertionError("provider must stay lazy"))
        activity = legacy(
            {"questions": [{"id": "q1", "type": "single_choice", "prompt": "选择"}]},
            {"q1": {"answer": "a", "explanation": "说明"}},
        )
        result = asyncio.run(AttemptSubmissionService(
            short_answer_evaluator_factory=factory,
        ).evaluate(activity, {"q1": "a"}))
        self.assertEqual(result.score, 100)
        factory.assert_not_called()

    def test_attempt_result_contains_no_answer_key(self):
        evaluator = AsyncMock(return_value=Evaluation(100))
        activity = legacy(
            {"questions": [{"id": "q1", "type": "short_answer", "prompt": "解释"}]},
            {"q1": {"reference_answer": "机密参考答案", "rubric": ["隐藏评分点"]}},
        )
        result = asyncio.run(AttemptSubmissionService(short_answer_evaluator=evaluator).evaluate(activity, {"q1": "回答"}))
        encoded = json.dumps(result.result_dict(), ensure_ascii=False)
        # referenceAnswer is part of the existing public result contract; the
        # private answer-key shape and rubric must not leak into the result.
        self.assertNotIn('"answer"', encoded)
        self.assertNotIn("隐藏评分点", encoded)


if __name__ == "__main__":
    unittest.main()
