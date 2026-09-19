import inspect
import json
import unittest
from datetime import datetime
from types import SimpleNamespace

from backend.services import activity_assessment, activity_hooks, activity_query
from backend.services import activity_workflow


def _attempt(result):
    return SimpleNamespace(
        id="attempt-1",
        activity_id="activity-1",
        status="evaluated",
        score=70,
        mastery_level="developing",
        diagnostic_summary="诊断",
        result_json=json.dumps(result, ensure_ascii=False),
        created_at=datetime(2026, 1, 1),
        completed_at=None,
    )


class ActivityWorkflowBoundaryTests(unittest.TestCase):
    def test_compatibility_module_reexports_each_split_service_boundary(self):
        for name in (
            "activity_attempt_response",
            "activity_response",
            "get_activity",
        ):
            self.assertIs(
                getattr(activity_workflow, name),
                getattr(activity_query, name),
                name,
            )
        for name in ("generate_quiz", "submit_attempt", "submit_follow_up"):
            self.assertIs(
                getattr(activity_workflow, name),
                getattr(activity_assessment, name),
                name,
            )
        for name in (
            "run_post_assessment_hooks",
            "derive_effective_post_assessment",
            "should_run_activity_gap_diagnosis",
        ):
            self.assertIs(
                getattr(activity_workflow, name),
                getattr(activity_hooks, name),
                name,
            )

    def test_split_services_do_not_depend_on_router_or_compatibility_module(self):
        for module in (activity_query, activity_assessment, activity_hooks):
            source = inspect.getsource(module)
            self.assertNotIn("activity_api", source, module.__name__)
            self.assertNotIn("activity_workflow", source, module.__name__)

    def test_public_attempt_projection_is_an_explicit_allowlist(self):
        attempt = _attempt({
            "items": [{
                "questionId": "q1",
                "correct": False,
                "score": 40,
                "feedback": "继续思考",
                "referenceAnswer": "公开参考",
                "answer": "机密答案",
                "rubric": ["隐藏评分点"],
                "providerPayload": {"raw": "secret"},
            }],
            "followUp": {
                "id": "follow-up-1",
                "parentTaskId": "q1",
                "prompt": "补充说明",
                "status": "pending",
                "answer": "不应出现",
                "privateRubricIndex": 2,
            },
        })

        response = activity_query.activity_attempt_response(attempt)
        encoded = json.dumps(response, ensure_ascii=False, default=str)
        self.assertEqual(
            set(response["results"][0]),
            {"questionId", "correct", "score", "feedback", "referenceAnswer"},
        )
        self.assertNotIn("机密答案", encoded)
        self.assertNotIn("隐藏评分点", encoded)
        self.assertNotIn("providerPayload", encoded)
        self.assertNotIn("privateRubricIndex", encoded)
        self.assertNotIn('"answer"', encoded)

    def test_hook_derivation_keeps_follow_up_and_legacy_paths_distinct(self):
        self.assertEqual(
            activity_hooks.derive_effective_post_assessment(
                {"postFollowUpMastery": "developing"},
                50,
                "needs_review",
                "旧诊断",
            ),
            (
                "developing",
                60,
                "完成针对性追问后，当前掌握程度为：developing。",
            ),
        )
        self.assertEqual(
            activity_hooks.derive_effective_post_assessment(
                {}, 70, "developing", "旧诊断"
            ),
            ("developing", 70, "旧诊断"),
        )
        self.assertTrue(
            activity_hooks.should_run_activity_gap_diagnosis(
                {}, effective_mastery="needs_review"
            )
        )
        self.assertFalse(
            activity_hooks.should_run_activity_gap_diagnosis(
                {"lowConfidence": True}, effective_mastery="needs_review"
            )
        )
        self.assertFalse(
            activity_hooks.should_run_activity_gap_diagnosis(
                {"postFollowUpMastery": "developing"},
                effective_mastery="developing",
            )
        )


if __name__ == "__main__":
    unittest.main()
