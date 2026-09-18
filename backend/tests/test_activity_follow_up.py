import asyncio
import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend import api
from backend.schemas import SubmitActivityFollowUpRequest


def activity():
    return SimpleNamespace(
        id="activity-1", section_id="section-1", card_id="card-1",
        objective="目标", content_json=json.dumps({"questions": []}),
        answer_key_json=json.dumps({}),
    )


def attempt(status="follow_up_pending"):
    return SimpleNamespace(
        id="attempt-1", activity_id="activity-1", status=status,
        score=50, mastery_level="developing", diagnostic_summary="诊断",
        result_json=json.dumps({
            "items": [],
            "followUp": {
                "id": "follow-up-q1-1", "parentTaskId": "q1", "prompt": "补充",
                "status": "pending", "privateParentQuestionId": "q1",
                "privateRubricIndex": 0,
            },
        }, ensure_ascii=False),
        completed_at=None, created_at=datetime.utcnow(),
    )


class FollowUpEndpointTests(unittest.TestCase):
    def test_success_updates_same_attempt_and_does_not_add_attempt(self):
        current = attempt()
        section = SimpleNamespace(content_markdown="内容")
        card = SimpleNamespace(id="card-1", title="卡片")
        db = MagicMock()
        db.get.side_effect = [current, section, card]
        evaluator = SimpleNamespace(score=80, feedback="很好")
        service = MagicMock()
        service.evaluate_follow_up = AsyncMock(return_value=evaluator)
        with patch("backend.api._get_activity", return_value=activity()), \
             patch("backend.api.AttemptSubmissionService", return_value=service), \
             patch("backend.api.restore_active_provider"), \
             patch("backend.api._run_activity_post_assessment_hooks", new_callable=AsyncMock):
            response = asyncio.run(api.submit_activity_follow_up(
                "activity-1", "attempt-1", SubmitActivityFollowUpRequest(answer="补充回答"), db
            ))
        self.assertEqual(response["id"], "attempt-1")
        self.assertEqual(current.status, "evaluated")
        self.assertEqual(json.loads(current.result_json)["postFollowUpMastery"], "developing")
        db.add.assert_not_called()
        db.commit.assert_called()

    def test_completed_follow_up_returns_409(self):
        current = attempt()
        current.result_json = json.dumps({"followUp": {"status": "completed"}})
        db = MagicMock()
        db.get.return_value = current
        with patch("backend.api._get_activity", return_value=activity()):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(api.submit_activity_follow_up(
                    "activity-1", "attempt-1", SubmitActivityFollowUpRequest(answer="回答"), db
                ))
        self.assertEqual(caught.exception.status_code, 409)

    def test_evaluator_failure_keeps_pending_attempt_without_commit(self):
        current = attempt()
        original = current.result_json
        db = MagicMock()
        db.get.side_effect = [current, SimpleNamespace(content_markdown="内容")]
        service = MagicMock()
        service.evaluate_follow_up = AsyncMock(side_effect=RuntimeError("provider"))
        with patch("backend.api._get_activity", return_value=activity()), \
             patch("backend.api.AttemptSubmissionService", return_value=service), \
             patch("backend.api.restore_active_provider"):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(api.submit_activity_follow_up(
                    "activity-1", "attempt-1", SubmitActivityFollowUpRequest(answer="回答"), db
                ))
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(current.status, "follow_up_pending")
        self.assertEqual(current.result_json, original)
        db.commit.assert_not_called()

    def test_attempt_from_another_activity_returns_404(self):
        current = attempt()
        current.activity_id = "other-activity"
        db = MagicMock()
        db.get.return_value = current
        with patch("backend.api._get_activity", return_value=activity()):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(api.submit_activity_follow_up(
                    "activity-1", "attempt-1", SubmitActivityFollowUpRequest(answer="回答"), db
                ))
        self.assertEqual(caught.exception.status_code, 404)

    def test_public_projection_filters_private_follow_up_fields(self):
        current = attempt()
        public = api._activity_attempt_response(current)
        encoded = json.dumps(public, ensure_ascii=False, default=str)
        self.assertIn("follow-up-q1-1", encoded)
        self.assertNotIn("privateRubricIndex", encoded)
        self.assertNotIn("privateParentQuestionId", encoded)
        self.assertNotIn("\"answer\"", encoded)

    def test_low_confidence_disables_automatic_gap_diagnosis(self):
        self.assertFalse(api.should_run_activity_gap_diagnosis({"lowConfidence": True}))
        self.assertTrue(api.should_run_activity_gap_diagnosis({"lowConfidence": False}, effective_mastery="needs_review"))

    def test_post_follow_up_developing_overrides_old_score_for_hooks(self):
        mastery, score, diagnostic = api.derive_effective_post_assessment(
            {"postFollowUpMastery": "developing"}, 50, "needs_review", "旧诊断"
        )
        self.assertEqual((mastery, score), ("developing", 60))
        self.assertIn("针对性追问", diagnostic)
        self.assertFalse(api.should_run_activity_gap_diagnosis(
            {"postFollowUpMastery": "developing"}, effective_mastery=mastery
        ))

    def test_follow_up_failure_needs_review_keeps_gap_eligible(self):
        mastery, score, diagnostic = api.derive_effective_post_assessment(
            {}, 50, "needs_review", "旧诊断"
        )
        self.assertEqual((mastery, score, diagnostic), ("needs_review", 50, "旧诊断"))
        self.assertTrue(api.should_run_activity_gap_diagnosis({}, effective_mastery=mastery))

    def test_without_post_follow_up_field_preserves_old_hook_values(self):
        self.assertEqual(
            api.derive_effective_post_assessment({}, 70, "developing", "旧诊断"),
            ("developing", 70, "旧诊断"),
        )


if __name__ == "__main__":
    unittest.main()
