import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend import activity_api
from backend.agents.schemas import (
    QuizAnswerKey,
    QuizDraft,
    QuizOption,
    QuizQuestion,
)
from backend.services import activity_workflow


def _draft():
    return QuizDraft(
        title="理解检查",
        objective="掌握核心概念",
        questions=[
            QuizQuestion(
                id="q1",
                type="single_choice",
                prompt="核心概念是什么？",
                options=[QuizOption(id="a", text="答案")],
            )
        ],
        answer_key=[
            QuizAnswerKey(
                question_id="q1",
                answer="a",
                explanation="解释",
            )
        ],
    )


def _activity(status="generating"):
    return SimpleNamespace(
        id="activity-1",
        card_id="card-1",
        section_id="section-1",
        activity_type="quiz",
        title="理解检查",
        objective="检查理解",
        status=status,
        content_json="{}",
        answer_key_json="{}",
        generation_error=None,
        created_at=None,
    )


class ActivityQuizGenerationTests(unittest.TestCase):
    def setUp(self):
        self.card = SimpleNamespace(id="card-1", title="卡片", status="active")
        self.section = SimpleNamespace(
            id="section-1",
            card_id="card-1",
            title="章节",
            content_markdown="章节内容",
            teaching_objective="检查理解",
        )

    def _db(self, activity):
        db = MagicMock()
        db.scalar.return_value = activity
        db.get.side_effect = [self.section, self.card]
        return db

    def test_generation_failure_persists_failed_state_and_error(self):
        activity = _activity()
        db = self._db(activity)
        agent = MagicMock()
        agent.generate_quiz = AsyncMock(side_effect=RuntimeError("provider failed"))
        with patch("backend.activity_api.owned_card", return_value=self.card), \
             patch("backend.services.activity_workflow.AssessmentAgent", return_value=agent), \
             patch("backend.services.activity_workflow.restore_active_provider"):
            with self.assertRaises(RuntimeError):
                asyncio.run(activity_api.generate_section_quiz(
                    "card-1", "section-1", db
                ))
        self.assertEqual(activity.status, "failed")
        self.assertEqual(activity.generation_error, "provider failed")
        db.commit.assert_called()

    def test_success_persists_ready_quiz_but_public_response_has_no_answer_key(self):
        activity = _activity()
        db = self._db(activity)
        agent = MagicMock()
        agent.generate_quiz = AsyncMock(return_value=_draft())
        with patch("backend.activity_api.owned_card", return_value=self.card), \
             patch("backend.services.activity_workflow.AssessmentAgent", return_value=agent), \
             patch("backend.services.activity_workflow.restore_active_provider"):
            response = asyncio.run(activity_api.generate_section_quiz(
                "card-1", "section-1", db
            ))
        self.assertEqual(activity.status, "ready")
        self.assertEqual(response["questions"][0]["id"], "q1")
        encoded = json.dumps(response, ensure_ascii=False, default=str)
        self.assertNotIn("answer_key", encoded)
        self.assertNotIn('"answer"', encoded)
        self.assertIn("a", activity.answer_key_json)
        agent.generate_quiz.assert_awaited_once()

    def test_owned_activity_missing_or_cross_user_is_not_found(self):
        class QueryAwareDB:
            def __init__(self):
                self.statements = []

            def scalar(self, statement):
                self.statements.append(statement)
                return None

        for activity_id in ("missing", "owned-by-another-user"):
            db = QueryAwareDB()
            with patch.object(
                activity_workflow, "current_user_id", return_value="user-1"
            ) as current_user:
                with self.assertRaises(HTTPException) as caught:
                    activity_workflow.get_activity(activity_id, db)
            self.assertEqual(caught.exception.status_code, 404)
            self.assertEqual(caught.exception.detail, "Learning activity not found")
            current_user.assert_called_once_with()
            self.assertEqual(len(db.statements), 1)
            statement = str(db.statements[0])
            self.assertIn("learning_activities", statement)
            self.assertIn("learning_spaces", statement)


if __name__ == "__main__":
    unittest.main()
