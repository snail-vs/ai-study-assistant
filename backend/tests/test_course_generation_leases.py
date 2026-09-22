import asyncio
import unittest
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db import Base
from backend.models import LearningSpace, now
from backend.services import course_generation


class CourseGenerationLeaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        course_generation.course_generation_tasks.clear()
        course_generation.scheduled_generation_tokens.clear()

    def tearDown(self):
        course_generation.course_generation_tasks.clear()
        course_generation.scheduled_generation_tokens.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def add_space(self, **values):
        space = LearningSpace(
            id="space-1",
            user_id="user-1",
            title="课程",
            learning_goal="学习 Python",
            generation_status="queued",
            generation_phase="queued",
            **values,
        )
        with Session(self.engine) as db:
            db.add(space)
            db.commit()

    def test_live_lease_is_not_claimed_twice(self):
        self.add_space()
        first = Session(self.engine)
        second = Session(self.engine)
        try:
            token = course_generation.claim_generation_lease(
                first, "space-1", owner="worker-a", token="token-a"
            )
            first.commit()
            rejected = course_generation.claim_generation_lease(
                second, "space-1", owner="worker-b", token="token-b"
            )
            self.assertEqual(token, "token-a")
            self.assertIsNone(rejected)
            self.assertEqual(first.get(LearningSpace, "space-1").generation_lease_owner, "worker-a")
        finally:
            first.close()
            second.close()

    def test_expired_lease_can_be_reclaimed(self):
        expired = now() - timedelta(seconds=1)
        self.add_space(
            generation_lease_owner="old-worker",
            generation_lease_token="old-token",
            generation_lease_expires_at=expired,
        )
        with Session(self.engine) as db:
            token = course_generation.claim_generation_lease(
                db, "space-1", owner="new-worker", token="new-token"
            )
            db.commit()
            space = db.get(LearningSpace, "space-1")
            self.assertEqual(token, "new-token")
            self.assertEqual(space.generation_lease_owner, "new-worker")
            self.assertEqual(space.generation_lease_token, "new-token")
            self.assertGreater(space.generation_lease_expires_at, now())

    def test_failed_generation_releases_lease(self):
        self.add_space()
        with (
            patch.object(course_generation, "SessionLocal", return_value=Session(self.engine)),
            patch.object(
                course_generation,
                "restore_active_provider",
                side_effect=RuntimeError("provider unavailable"),
            ),
        ):
            asyncio.run(course_generation.generate_course("space-1", "user-1", "goal"))

        with Session(self.engine) as db:
            space = db.get(LearningSpace, "space-1")
            self.assertEqual(space.generation_status, "failed")
            self.assertIsNone(space.generation_lease_token)
            self.assertIsNone(space.generation_lease_expires_at)

    def test_cancelled_generation_releases_lease(self):
        self.add_space()

        async def cancelled(*_args, **_kwargs):
            raise asyncio.CancelledError

        with (
            patch.object(
                course_generation,
                "SessionLocal",
                side_effect=lambda: Session(self.engine),
            ),
            patch.object(course_generation, "restore_active_provider", return_value=object()),
            patch.object(course_generation.MainAgent, "plan_course", new=cancelled),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(course_generation.generate_course("space-1", "user-1", "goal"))

        with Session(self.engine) as db:
            space = db.get(LearningSpace, "space-1")
            self.assertIsNone(space.generation_lease_token)
            self.assertIsNone(space.generation_lease_expires_at)

    def test_startup_recovery_schedules_persisted_work(self):
        self.add_space()
        with Session(self.engine) as db:
            space = db.get(LearningSpace, "space-1")
            space.generation_status = "running"
            space.generation_lease_expires_at = now() - timedelta(seconds=1)
            db.commit()

        session = Session(self.engine)
        with patch.object(course_generation, "SessionLocal", return_value=session), patch.object(
            course_generation, "schedule_course_generation"
        ) as schedule:
            asyncio.run(course_generation.resume_pending_course_generations())
        schedule.assert_called_once_with("space-1", "user-1", "学习 Python", {}, "standard")

    def test_schedule_does_not_create_task_when_another_worker_holds_lease(self):
        self.add_space()
        with Session(self.engine) as db:
            self.assertEqual(
                course_generation.claim_generation_lease(
                    db, "space-1", owner="worker-a", token="token-a"
                ),
                "token-a",
            )
            db.commit()

        with (
            patch.object(course_generation, "SessionLocal", return_value=Session(self.engine)),
            patch.object(asyncio, "create_task") as create_task,
        ):
            course_generation.schedule_course_generation("space-1", "user-1", "学习 Python")

        create_task.assert_not_called()
        self.assertNotIn("space-1", course_generation.course_generation_tasks)


if __name__ == "__main__":
    unittest.main()
