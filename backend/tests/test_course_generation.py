import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.agents.main_agent import MainAgent
from backend.agents.schemas import (
    CardSectionDraft,
    KnowledgeCardPlanDraft,
    SectionPlanDraft,
)
from backend.db import Base
from backend.models import CardSection, KnowledgeCard, LearningSpace
from backend.services import course_generation


def _plan():
    return KnowledgeCardPlanDraft(
        title="Python 基础",
        summary="入门课程",
        sections=[
            SectionPlanDraft(
                title="变量",
                teaching_objective="理解变量",
                content_type="concept",
                key_concepts=["变量"],
            ),
            SectionPlanDraft(
                title="练习",
                teaching_objective="使用变量",
                content_type="practice",
                prerequisites=["变量"],
            ),
        ],
    )


def _section(title, content, content_type="concept"):
    return CardSectionDraft(
        title=title,
        content_markdown=content,
        content_type=content_type,
        teaching_objective=f"学习{title}",
        quality_report={"quality_status": "passed"},
        plan={"title": title},
        actual_summary={
            "actually_taught": [title],
            "summary": f"已讲授{title}",
        },
    )


def _agent(*section_results, plan=None):
    return SimpleNamespace(
        plan_course=AsyncMock(return_value=plan or _plan()),
        build_section_context=MainAgent.build_section_context,
        generate_section=AsyncMock(side_effect=list(section_results)),
    )


class CourseGenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        course_generation.course_generation_tasks.clear()
        course_generation.scheduled_generation_tokens.clear()
        with Session(self.engine) as db:
            db.add(LearningSpace(
                id="space-1",
                user_id="user-1",
                title="课程",
                learning_goal="学习 Python",
                generation_status="queued",
                generation_phase="queued",
            ))
            db.commit()
        self.session_factory = lambda: Session(self.engine, expire_on_commit=False)

    def tearDown(self):
        course_generation.course_generation_tasks.clear()
        course_generation.scheduled_generation_tokens.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    async def test_generate_course_persists_each_section_and_completed_state(self):
        fake_agent = _agent(
            _section("变量", "变量正文"),
            _section("练习", "练习正文", "practice"),
        )
        with (
            patch.object(course_generation, "SessionLocal", side_effect=self.session_factory),
            patch.object(course_generation, "restore_active_provider", return_value=object()),
            patch.object(course_generation, "MainAgent", return_value=fake_agent),
        ):
            await course_generation.generate_course("space-1", "user-1", "学习 Python")

        with Session(self.engine) as db:
            space = db.get(LearningSpace, "space-1")
            card = db.get(KnowledgeCard, space.root_card_id)
            sections = list(db.scalars(
                select(CardSection).where(CardSection.card_id == card.id).order_by(CardSection.order_index)
            ))
            self.assertEqual(space.generation_status, "completed")
            self.assertEqual(space.generation_phase, "completed")
            self.assertEqual(card.status, "active")
            self.assertEqual(card.summary, "入门课程")
            self.assertEqual([item.generation_status for item in sections], ["completed", "completed"])
            self.assertEqual([item.generation_attempts for item in sections], [1, 1])
            self.assertEqual(sections[0].actual_summary["actually_taught"], ["变量"])
            self.assertEqual(sections[1].content_type, "practice")
        self.assertEqual(fake_agent.generate_section.await_count, 2)

    async def test_failed_section_is_persisted_and_retry_resumes_from_it(self):
        first_agent = _agent(
            _section("变量", "变量正文"),
            RuntimeError("second section failed"),
        )
        with (
            patch.object(course_generation, "SessionLocal", side_effect=self.session_factory),
            patch.object(course_generation, "restore_active_provider", return_value=object()),
            patch.object(course_generation, "MainAgent", return_value=first_agent),
        ):
            await course_generation.generate_course("space-1", "user-1", "学习 Python")

        with Session(self.engine) as db:
            space = db.get(LearningSpace, "space-1")
            card = db.get(KnowledgeCard, space.root_card_id)
            sections = list(db.scalars(
                select(CardSection).where(CardSection.card_id == card.id).order_by(CardSection.order_index)
            ))
            self.assertEqual(space.generation_status, "failed")
            self.assertEqual(card.status, "draft")
            self.assertEqual([item.generation_status for item in sections], ["completed", "failed"])
            space.generation_status = "queued"
            space.generation_phase = "queued"
            db.commit()

        retry_agent = _agent(_section("练习", "恢复后的练习", "practice"))
        with (
            patch.object(course_generation, "SessionLocal", side_effect=self.session_factory),
            patch.object(course_generation, "restore_active_provider", return_value=object()),
            patch.object(course_generation, "MainAgent", return_value=retry_agent),
        ):
            await course_generation.generate_course("space-1", "user-1", "学习 Python")

        retry_agent.plan_course.assert_not_awaited()
        retry_agent.generate_section.assert_awaited_once()
        with Session(self.engine) as db:
            space = db.get(LearningSpace, "space-1")
            card = db.get(KnowledgeCard, space.root_card_id)
            sections = list(db.scalars(
                select(CardSection).where(CardSection.card_id == card.id).order_by(CardSection.order_index)
            ))
            self.assertEqual(space.generation_status, "completed")
            self.assertEqual(card.status, "active")
            self.assertEqual([item.generation_attempts for item in sections], [1, 2])
            self.assertEqual(sections[1].content_markdown, "恢复后的练习")

    async def test_missing_space_exits_and_cleans_registry(self):
        with Session(self.engine) as db:
            db.delete(db.get(LearningSpace, "space-1"))
            db.commit()
        course_generation.course_generation_tasks["space-1"] = SimpleNamespace()
        with patch.object(course_generation, "SessionLocal", side_effect=self.session_factory):
            await course_generation.generate_course("space-1", "user-1", "goal")
        self.assertNotIn("space-1", course_generation.course_generation_tasks)

    async def test_provider_failure_persists_failed_state(self):
        with (
            patch.object(course_generation, "SessionLocal", side_effect=self.session_factory),
            patch.object(
                course_generation,
                "restore_active_provider",
                side_effect=RuntimeError("provider unavailable"),
            ),
        ):
            await course_generation.generate_course("space-1", "user-1", "goal")
        with Session(self.engine) as db:
            space = db.get(LearningSpace, "space-1")
            self.assertEqual(space.generation_status, "failed")
            self.assertEqual(space.generation_error, "provider unavailable")
            self.assertIsNone(space.generation_lease_token)

    async def test_cancelled_plan_releases_lease_and_propagates(self):
        fake_agent = _agent()
        fake_agent.plan_course.side_effect = asyncio.CancelledError
        with (
            patch.object(course_generation, "SessionLocal", side_effect=self.session_factory),
            patch.object(course_generation, "restore_active_provider", return_value=object()),
            patch.object(course_generation, "MainAgent", return_value=fake_agent),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await course_generation.generate_course("space-1", "user-1", "goal")
        with Session(self.engine) as db:
            space = db.get(LearningSpace, "space-1")
            self.assertIsNone(space.generation_lease_token)

    async def test_schedule_deduplicates_running_task_and_replaces_done_task(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_generate(space_id, user_id, learning_goal):
            started.set()
            await release.wait()

        with (
            patch.object(course_generation, "SessionLocal", side_effect=self.session_factory),
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
            course_generation.schedule_course_generation("space-1", "user-1", "goal-3")
            await course_generation.course_generation_tasks["space-1"]
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
        session.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
