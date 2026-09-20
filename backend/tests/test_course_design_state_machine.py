import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.ai.providers.mock import MockTextProvider
from backend.db import Base
from backend.models import User
from backend.schemas import CourseDesignCommandRequest
from backend.services.course_design import CourseDesignConflict, CourseDesignInvalid, CourseDesignService
from backend.models import CourseDesignSession, LearningSpace


class CourseDesignStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(User(id="user-1", username="user-1", password_hash="hash"))
        self.db.commit()
        self.service = CourseDesignService(self.db, "user-1", MockTextProvider())

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def command(self, session, command_id, kind, payload=None, revision=None):
        return asyncio.run(self.service.execute(
            session.session_id,
            CourseDesignCommandRequest(
                commandId=command_id,
                expectedRevision=session.revision if revision is None else revision,
                type=kind,
                payload=payload or {},
            ),
        ))

    def test_explicit_state_flow_and_multiple_selection(self):
        session = asyncio.run(self.service.create("Kubernetes Operator"))
        self.assertEqual(session.state, "collecting_goals")
        session = self.command(session, "goals", "answer_question", {"answer": {
            "questionId": session.current_question.id,
            "selectedOptionIds": ["understand-core", "hands-on"],
            "customText": "能够独立开发一个 Operator",
        }})
        self.assertEqual(session.state, "collecting_background")
        self.assertEqual(session.brief.learning_goals, ["理解核心原理与架构", "能够动手完成实践"])

    def test_stale_revision_and_illegal_transition_are_rejected(self):
        session = asyncio.run(self.service.create("Python"))
        with self.assertRaises(CourseDesignConflict):
            self.command(session, "bad", "generate_outline")
        self.command(session, "goals", "complete_with_ai")
        with self.assertRaises(CourseDesignConflict):
            self.command(session, "stale", "complete_with_ai", revision=1)

    def test_duplicate_command_is_idempotent(self):
        session = asyncio.run(self.service.create("Python"))
        first = self.command(session, "same", "complete_with_ai")
        second = self.command(first, "same", "complete_with_ai")
        self.assertEqual(first.revision, second.revision)
        self.assertEqual(first.state, second.state)

    def test_outline_requires_scale_and_confirmation(self):
        session = asyncio.run(self.service.create("Python"))
        session = self.command(session, "goals", "complete_with_ai")
        session = self.command(session, "background", "complete_with_ai")
        session = self.command(session, "scale", "select_scale", {"courseScale": "quick"})
        session = self.command(session, "outline", "generate_outline")
        self.assertEqual(session.state, "reviewing_outline")
        with self.assertRaises(CourseDesignConflict):
            self.command(session, "course", "generate_course")
        session = self.command(session, "confirm", "confirm_outline")
        self.assertEqual(session.state, "outline_confirmed")

    def test_brief_change_invalidates_outline(self):
        session = asyncio.run(self.service.create("Python"))
        session = self.command(session, "goals", "complete_with_ai")
        session = self.command(session, "background", "complete_with_ai")
        session = self.command(session, "scale", "select_scale", {"courseScale": "quick"})
        session = self.command(session, "outline", "generate_outline")
        session = self.command(session, "back", "go_back")
        session = self.command(session, "edit", "update_brief", {"brief": {"learningOutcome": "完成一个可运行项目"}})
        self.assertEqual(session.outline, [])
        with self.assertRaises(CourseDesignConflict):
            self.command(session, "confirm", "confirm_outline")

    def test_get_does_not_initialize_provider(self):
        session = asyncio.run(self.service.create("Python"))
        with patch("backend.services.course_design.restore_active_provider", side_effect=RuntimeError("provider unavailable")):
            lazy = CourseDesignService(self.db, "user-1")
            snapshot = lazy.get(session.session_id)
        self.assertEqual(snapshot.session_id, session.session_id)

    def test_revision_feedback_and_outline_guards(self):
        session = asyncio.run(self.service.create("Python"))
        session = self.command(session, "goals", "complete_with_ai")
        session = self.command(session, "background", "complete_with_ai")
        with self.assertRaises(CourseDesignInvalid):
            self.command(session, "outline", "generate_outline")
        session = self.command(session, "scale", "select_scale", {"courseScale": "quick"})
        session = self.command(session, "outline", "generate_outline")
        with self.assertRaises(CourseDesignInvalid):
            self.command(session, "revise", "revise_outline", {"feedback": "  "})

    def test_generation_commits_session_and_space_once_before_schedule(self):
        session = asyncio.run(self.service.create("Python"))
        session = self.command(session, "goals", "complete_with_ai")
        session = self.command(session, "background", "complete_with_ai")
        session = self.command(session, "scale", "select_scale", {"courseScale": "quick"})
        session = self.command(session, "outline", "generate_outline")
        session = self.command(session, "confirm", "confirm_outline")
        with patch("backend.services.course_design.schedule_course_generation") as schedule:
            result = self.command(session, "course", "generate_course")
        self.assertEqual(result.state, "course_queued")
        self.assertEqual(self.db.query(LearningSpace).count(), 1)
        self.assertEqual(schedule.call_args.args[3], result.brief.model_dump(by_alias=True))

    def test_agent_patch_and_question_target_are_rejected(self):
        class MalformedAgent(MockTextProvider):
            async def structured(self, messages, *, task, schema):
                result = await super().structured(messages, task=task, schema=schema)
                if task == "course_intake_state" and "evaluate_intake_answer" in messages[-1]["content"]:
                    result["briefPatch"]["topic"] = "另一个主题"
                    result["nextQuestion"]["target"] = "learningGoals"
                return result

        service = CourseDesignService(self.db, "user-1", MalformedAgent())
        session = asyncio.run(service.create("Python"))
        with self.assertRaises(CourseDesignInvalid):
            asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
                commandId="malformed", expectedRevision=session.revision, type="answer_question",
                payload={"answer": {"questionId": session.current_question.id, "selectedOptionIds": ["understand-core"]}},
            )))

    def test_retry_requires_owned_failed_space_and_reuses_it(self):
        failed = LearningSpace(
            id="failed-space", user_id="user-1", title="旧课程", learning_goal="旧目标",
            generation_status="failed", generation_phase="failed", generation_error="provider",
        )
        active = LearningSpace(
            id="active-space", user_id="user-1", title="进行中", learning_goal="目标",
            generation_status="completed", generation_phase="completed",
        )
        self.db.add_all([failed, active])
        self.db.commit()
        retry = asyncio.run(self.service.create("Python", "failed-space"))
        retry = self.command(retry, "goals", "complete_with_ai")
        retry = self.command(retry, "background", "complete_with_ai")
        retry = self.command(retry, "scale", "select_scale", {"courseScale": "quick"})
        retry = self.command(retry, "outline", "generate_outline")
        retry = self.command(retry, "confirm", "confirm_outline")
        with patch("backend.services.course_design.schedule_course_generation"):
            result = self.command(retry, "course", "generate_course")
        self.assertEqual(result.operation["spaceId"], "failed-space")
        self.assertEqual(self.db.query(LearningSpace).count(), 2)
        self.assertEqual(self.db.get(LearningSpace, "failed-space").generation_status, "queued")
        with self.assertRaises(CourseDesignInvalid):
            asyncio.run(self.service.create("Python", "active-space"))
        with self.assertRaises(CourseDesignInvalid):
            asyncio.run(self.service.create("Python", "missing-space"))


if __name__ == "__main__":
    unittest.main()
