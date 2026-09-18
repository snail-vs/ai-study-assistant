import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from backend.services import activity_workflow
from backend.services import ownership


class OwnershipHelperTests(unittest.TestCase):
    def assert_not_found(self, helper, resource_id, detail):
        db = MagicMock()
        db.scalar.return_value = None
        with patch("backend.services.ownership.current_user_id", return_value="user-1"):
            with self.assertRaises(HTTPException) as caught:
                helper(db, resource_id)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail, detail)
        db.scalar.assert_called_once()

    def test_owned_space_returns_only_current_users_matching_space(self):
        space = SimpleNamespace(id="space-1", user_id="user-1")
        db = MagicMock()
        db.scalar.return_value = space
        with patch("backend.services.ownership.current_user_id", return_value="user-1") as current_user:
            self.assertIs(ownership.owned_space(db, "space-1"), space)
        current_user.assert_called_once_with()
        db.scalar.assert_called_once()

    def test_owned_space_rejects_missing_or_other_users_space(self):
        self.assert_not_found(ownership.owned_space, "space-foreign", "Learning space not found")

    def test_owned_card_returns_only_current_users_card(self):
        card = SimpleNamespace(id="card-1", space_id="space-1")
        db = MagicMock()
        db.scalar.return_value = card
        with patch("backend.services.ownership.current_user_id", return_value="user-1") as current_user:
            self.assertIs(ownership.owned_card(db, "card-1"), card)
        current_user.assert_called_once_with()
        db.scalar.assert_called_once()

    def test_owned_card_rejects_missing_or_other_users_card(self):
        self.assert_not_found(ownership.owned_card, "card-foreign", "Knowledge card not found")

    def test_owned_conversation_returns_only_current_users_conversation(self):
        conversation = SimpleNamespace(id="conversation-1", card_id="card-1")
        db = MagicMock()
        db.scalar.return_value = conversation
        with patch("backend.services.ownership.current_user_id", return_value="user-1") as current_user:
            self.assertIs(ownership.owned_conversation(db, "conversation-1"), conversation)
        current_user.assert_called_once_with()
        db.scalar.assert_called_once()

    def test_owned_conversation_rejects_missing_or_other_users_conversation(self):
        self.assert_not_found(ownership.owned_conversation, "conversation-foreign", "Conversation not found")


class ActivityResponseHelperTests(unittest.TestCase):
    def test_attempt_response_whitelists_items_and_nested_follow_up_result(self):
        attempt = SimpleNamespace(
            id="attempt-1",
            activity_id="activity-1",
            status="evaluated",
            score=80,
            mastery_level="developing",
            diagnostic_summary="诊断",
            created_at=datetime(2026, 1, 1),
            completed_at=datetime(2026, 1, 2),
            result_json=json.dumps({
                "items": [
                    {
                        "questionId": "q1",
                        "correct": True,
                        "score": 80,
                        "feedback": "很好",
                        "referenceAnswer": "参考",
                        "confidence": 0.9,
                        "providerPayload": {"secret": "do-not-leak"},
                        "privateRubricIndex": 3,
                    },
                    "malformed-item",
                    None,
                ],
                "followUp": {
                    "id": "follow-up-1",
                    "parentTaskId": "q1",
                    "prompt": "补充说明",
                    "status": "pending",
                    "result": {"score": 70, "feedback": "已完成"},
                    "answer": "private-answer",
                    "privateParentQuestionId": "q1",
                },
                "postFollowUpMastery": "mastered",
                "privateProviderPayload": {"raw": "secret"},
            }, ensure_ascii=False),
        )

        response = activity_workflow.activity_attempt_response(attempt)

        self.assertEqual(response["results"], [{
            "questionId": "q1",
            "correct": True,
            "score": 80,
            "feedback": "很好",
            "referenceAnswer": "参考",
            "confidence": 0.9,
        }])
        self.assertEqual(response["followUp"], {
            "id": "follow-up-1",
            "parentTaskId": "q1",
            "prompt": "补充说明",
            "status": "pending",
            "result": {"score": 70, "feedback": "已完成"},
        })
        encoded = json.dumps(response, ensure_ascii=False, default=str)
        self.assertNotIn("providerPayload", encoded)
        self.assertNotIn("privateRubricIndex", encoded)
        self.assertNotIn("private-answer", encoded)
        self.assertNotIn("privateProviderPayload", encoded)

    def test_attempt_response_handles_none_and_invalid_follow_up_shape(self):
        self.assertIsNone(activity_workflow.activity_attempt_response(None))
        attempt = SimpleNamespace(
            id="attempt-2", activity_id="activity-2", status="evaluated", score=None,
            mastery_level=None, diagnostic_summary=None, created_at=None, completed_at=None,
            result_json=json.dumps({"items": [{"questionId": "q1"}], "followUp": "invalid"}),
        )
        response = activity_workflow.activity_attempt_response(attempt)
        self.assertEqual(response["results"], [{"questionId": "q1"}])
        self.assertIsNone(response["followUp"])

    def test_activity_response_projects_questions_and_latest_attempt(self):
        activity = SimpleNamespace(
            id="activity-1", card_id="card-1", section_id="section-1",
            activity_type="quiz", title="测验", objective="目标", status="ready",
            content_json=json.dumps({"questions": [{"id": "q1", "prompt": "问题"}], "answerKey": "secret"}),
            created_at=datetime(2026, 1, 1),
        )
        attempt = SimpleNamespace(
            id="attempt-1", activity_id="activity-1", status="evaluated", score=100,
            mastery_level="mastered", diagnostic_summary="完成", result_json='{"items": []}',
            created_at=None, completed_at=None,
        )
        with patch(
            "backend.services.activity_workflow.activity_attempt_response",
            wraps=activity_workflow.activity_attempt_response,
        ) as projector:
            response = activity_workflow.activity_response(activity, attempt)
        self.assertEqual(response["questions"], [{"id": "q1", "prompt": "问题"}])
        self.assertNotIn("answerKey", response)
        self.assertEqual(response["latestAttempt"]["id"], "attempt-1")
        projector.assert_called_once_with(attempt)

    def test_activity_response_uses_empty_questions_for_missing_content(self):
        activity = SimpleNamespace(
            id="activity-2", card_id="card-2", section_id="section-2",
            activity_type="quiz", title="测验", objective=None, status="generating",
            content_json="{}", created_at=None,
        )
        response = activity_workflow.activity_response(activity)
        self.assertEqual(response["questions"], [])
        self.assertIsNone(response["latestAttempt"])


if __name__ == "__main__":
    unittest.main()
