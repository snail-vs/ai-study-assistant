import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db import Base
from backend.learning_space_api import delete_failed_learning_space
from backend.models import CourseDesignSession, LearningSpace, User
from unittest.mock import patch


class LearningSpaceDeleteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(User(id="user-1", username="user-1", password_hash="hash"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_deletes_failed_space_and_design_sessions(self):
        space = LearningSpace(
            id="space-1", user_id="user-1", title="失败课程", learning_goal="学习 Python",
            generation_status="failed", generation_phase="failed",
        )
        session = CourseDesignSession(
            id="session-1", user_id="user-1", source_learning_space_id="space-1", topic="Python",
        )
        self.db.add_all([space, session])
        self.db.commit()

        with patch("backend.services.ownership.current_user_id", return_value="user-1"):
            result = delete_failed_learning_space("space-1", self.db)

        self.assertEqual(result, {"status": "deleted", "spaceId": "space-1"})
        self.assertIsNone(self.db.get(LearningSpace, "space-1"))
        self.assertIsNone(self.db.get(CourseDesignSession, "session-1"))

    def test_rejects_non_failed_space(self):
        self.db.add(LearningSpace(
            id="space-1", user_id="user-1", title="进行中", learning_goal="目标",
            generation_status="running", generation_phase="generating",
        ))
        self.db.commit()

        with patch("backend.services.ownership.current_user_id", return_value="user-1"):
            with self.assertRaises(HTTPException) as raised:
                delete_failed_learning_space("space-1", self.db)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNotNone(self.db.get(LearningSpace, "space-1"))


if __name__ == "__main__":
    unittest.main()
