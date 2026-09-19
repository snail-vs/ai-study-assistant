import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agents.schemas import CardSectionDraft, KnowledgeCardDraft
from backend.models import CardSection, KnowledgeCard, LearningSpace
from backend.services import course_generation


def _draft():
    return KnowledgeCardDraft(
        title="Python 基础",
        summary="入门课程",
        sections=[
            CardSectionDraft(
                title="变量",
                content_markdown="# 变量",
                content_type="concept",
                teaching_objective="理解变量",
                quality_report={"quality": "good"},
            ),
            CardSectionDraft(
                title="",
                content_markdown="练习内容",
                content_type="practice",
                teaching_objective=None,
            ),
        ],
    )


class _Session:
    def __init__(self, space=None):
        self.space = space
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0
        self.flushed = 0

    def get(self, entity, identity):
        if entity is LearningSpace:
            return self.space if self.space is not None and self.space.id == identity else None
        raise AssertionError(f"unexpected get: {entity!r}")

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flushed += 1
        for value in self.added:
            if isinstance(value, KnowledgeCard) and value.id is None:
                value.id = "card-created"

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


class CourseGenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        course_generation.course_generation_tasks.clear()
        self.addCleanup(course_generation.course_generation_tasks.clear)
        self.space = LearningSpace(
            id="space-1",
            user_id="user-1",
            title="课程",
            learning_goal="学习 Python",
            generation_status="queued",
            generation_phase="queued",
        )

    async def test_generate_course_persists_card_sections_and_completed_state(self):
        first = _Session(self.space)
        second = _Session(self.space)
        with (
            patch.object(course_generation, "SessionLocal", side_effect=[first, second]),
            patch.object(course_generation, "restore_active_provider", return_value=object()) as restore,
            patch.object(course_generation, "MainAgent", return_value=SimpleNamespace(create_card=AsyncMock(return_value=_draft()))) as agent,
        ):
            await course_generation.generate_course("space-1", "user-1", "学习 Python")

        self.assertEqual(self.space.generation_status, "completed")
        self.assertEqual(self.space.generation_phase, "completed")
        self.assertIsNone(self.space.generation_error)
        self.assertEqual(self.space.root_card_id, "card-created")
        card = next(value for value in second.added if isinstance(value, KnowledgeCard))
        sections = [value for value in second.added if isinstance(value, CardSection)]
        self.assertEqual(card.title, "Python 基础")
        self.assertEqual(card.status, "active")
        self.assertEqual([section.title for section in sections], ["变量", "第 2 节"])
        self.assertEqual([section.order_index for section in sections], [0, 1])
        self.assertEqual(json.loads(sections[0].quality_report_json), {"quality": "good"})
        self.assertEqual([first.commits, second.commits], [1, 2])
        self.assertEqual([first.closed, second.closed], [1, 1])
        restore.assert_called_once_with(unittest.mock.ANY, "user-1")
        agent.return_value.create_card.assert_awaited_once_with("学习 Python", {}, "standard")

    async def test_missing_space_exits_and_cleans_registry(self):
        session = _Session(None)
        course_generation.course_generation_tasks["space-missing"] = SimpleNamespace()
        with patch.object(course_generation, "SessionLocal", return_value=session):
            await course_generation.generate_course("space-missing", "user-1", "goal")
        self.assertNotIn("space-missing", course_generation.course_generation_tasks)
        self.assertEqual(session.closed, 1)
        self.assertEqual(session.commits, 0)

    async def test_missing_space_after_generation_does_not_persist_card(self):
        first = _Session(self.space)
        second = _Session(None)
        draft = _draft()
        with (
            patch.object(course_generation, "SessionLocal", side_effect=[first, second]),
            patch.object(course_generation, "restore_active_provider", return_value=object()),
            patch.object(course_generation, "MainAgent", return_value=SimpleNamespace(create_card=AsyncMock(return_value=draft))),
        ):
            await course_generation.generate_course("space-1", "user-1", "goal")
        self.assertEqual(self.space.generation_status, "running")
        self.assertEqual(second.added, [])
        self.assertEqual(second.closed, 1)
        self.assertNotIn("space-1", course_generation.course_generation_tasks)

    async def test_provider_failure_rolls_back_and_persists_failed_state(self):
        session = _Session(self.space)
        with (
            patch.object(course_generation, "SessionLocal", return_value=session),
            patch.object(course_generation, "restore_active_provider", side_effect=RuntimeError("provider unavailable")),
        ):
            await course_generation.generate_course("space-1", "user-1", "goal")
        self.assertEqual(self.space.generation_status, "failed")
        self.assertEqual(self.space.generation_phase, "failed")
        self.assertEqual(self.space.generation_error, "provider unavailable")
        self.assertEqual(session.rollbacks, 1)
        self.assertEqual(session.commits, 2)
        self.assertEqual(session.closed, 1)

    async def test_agent_failure_after_session_release_persists_failed_state(self):
        first = _Session(self.space)
        failure_session = _Session(self.space)
        with (
            patch.object(course_generation, "SessionLocal", side_effect=[first, failure_session]),
            patch.object(course_generation, "restore_active_provider", return_value=object()),
            patch.object(course_generation, "MainAgent", return_value=SimpleNamespace(create_card=AsyncMock(side_effect=RuntimeError("agent failed")))),
        ):
            await course_generation.generate_course("space-1", "user-1", "goal")
        self.assertEqual(self.space.generation_status, "failed")
        self.assertEqual(self.space.generation_error, "agent failed")
        self.assertEqual(first.closed, 1)
        # The provider session was deliberately closed before the AI call; the
        # failure path opens a fresh session, so there is no pending transaction
        # left to roll back in that session.
        self.assertEqual(failure_session.rollbacks, 0)
        self.assertEqual(failure_session.commits, 1)
        self.assertEqual(failure_session.closed, 1)

    async def test_cancelled_error_propagates_and_task_registry_is_cleaned(self):
        session = _Session(self.space)
        with (
            patch.object(course_generation, "SessionLocal", return_value=session),
            patch.object(course_generation, "restore_active_provider", return_value=object()),
            patch.object(course_generation, "MainAgent", return_value=SimpleNamespace(create_card=AsyncMock(side_effect=asyncio.CancelledError))),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await course_generation.generate_course("space-1", "user-1", "goal")
        self.assertEqual(self.space.generation_status, "running")
        self.assertEqual(session.closed, 1)
        self.assertEqual(session.rollbacks, 0)
        self.assertNotIn("space-1", course_generation.course_generation_tasks)

    async def test_schedule_deduplicates_running_task_and_replaces_done_task(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_generate(space_id, user_id, learning_goal):
            started.set()
            await release.wait()

        with (
            patch.object(course_generation, "SessionLocal", return_value=_Session(self.space)),
            patch.object(course_generation, "claim_generation_lease", return_value="test-token"),
            patch.object(course_generation, "generate_course", side_effect=fake_generate) as generate,
        ):
            course_generation.schedule_course_generation("space-1", "user-1", "goal-1")
            await started.wait()
            first_task = course_generation.course_generation_tasks["space-1"]
            course_generation.schedule_course_generation("space-1", "user-1", "goal-2")
            self.assertIs(course_generation.course_generation_tasks["space-1"], first_task)
            self.assertEqual(generate.await_count, 1)
            release.set()
            await first_task
            self.assertIs(course_generation.course_generation_tasks["space-1"], first_task)
            course_generation.schedule_course_generation("space-1", "user-1", "goal-3")
            replacement = course_generation.course_generation_tasks["space-1"]
            self.assertIsNot(replacement, first_task)
            await replacement
            self.assertEqual(generate.await_count, 2)

    async def test_resume_schedules_queued_and_running_spaces_and_closes_session(self):
        queued = SimpleNamespace(
            id="queued", user_id="user-1", learning_goal="q", course_brief={}, course_scale="standard"
        )
        running = SimpleNamespace(
            id="running", user_id="user-2", learning_goal="r", course_brief={}, course_scale="standard"
        )
        session = MagicMock()
        session.scalars.return_value = [queued, running]
        with (
            patch.object(course_generation, "SessionLocal", return_value=session),
            patch.object(course_generation, "schedule_course_generation") as schedule,
        ):
            await course_generation.resume_pending_course_generations()
        schedule.assert_has_calls([
            unittest.mock.call("queued", "user-1", "q", {}, "standard"),
            unittest.mock.call("running", "user-2", "r", {}, "standard"),
        ])
        self.assertEqual(schedule.call_count, 2)
        session.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
