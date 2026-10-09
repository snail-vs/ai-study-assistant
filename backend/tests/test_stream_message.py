import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend import conversation_api
from backend.db import Base
from backend.models import (
    AIRun,
    CardSection,
    Conversation,
    KnowledgeCard,
    LearningSpace,
    Message,
    RelatedCardProposal,
    TeacherGuidance,
    User,
)
from backend.schemas import CreateMessageRequest
from backend.sse import encode_event
from backend.services.conversation_stream import ConversationStreamService


class SessionDouble:
    """Small unit-test seam for the streaming route's session contract."""

    def __init__(self, conversation, card, section=None, active_run=None):
        self.conversation = conversation
        self.card = card
        self.section = section
        self.active_run = active_run
        self.added = []
        self.commits = 0
        self._ids = {"Message": 0, "AIRun": 0, "TeacherGuidance": 0}

    def get(self, model, identifier):
        values = {
            (Conversation, self.conversation.id): self.conversation,
            (KnowledgeCard, self.card.id if self.card else None): self.card,
            (CardSection, self.section.id if self.section else None): self.section,
        }
        return values.get((model, identifier))

    def scalar(self, _statement):
        return self.active_run

    def scalars(self, _statement):
        return iter([
            item for item in self.added
            if isinstance(item, Message) and item.role == "user"
        ])

    def add(self, value):
        if isinstance(value, (Message, AIRun, TeacherGuidance)) and not value.id:
            name = value.__class__.__name__
            self._ids[name] += 1
            value.id = f"{name.lower()}-test-{self._ids[name]}"
        if isinstance(value, TeacherGuidance) and value.created_at is None:
            value.created_at = datetime.utcnow()
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def flush(self):
        return None

    def refresh(self, _value):
        return None


class AsyncTextStream:
    def __init__(self, values=None, error=None):
        self.values = list(values or [])
        self.error = error

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for value in self.values:
            yield value
        if self.error:
            raise self.error


def make_fixture(*, section_id="section-1", active_run=None):
    conversation = Conversation(
        id="conversation-1", card_id="card-1", section_id=section_id,
        conversation_type="side", title="讨论", root_question="起始问题",
        participant_ids_json='["teacher"]',
    )
    card = KnowledgeCard(id="card-1", space_id="space-1", title="知识卡", status="active")
    section = CardSection(
        id="section-1", card_id="card-1", title="章节", content_markdown="内容"
    )
    return conversation, card, section, SessionDouble(conversation, card, section, active_run)


def payload(section_id="section-1"):
    return CreateMessageRequest(content="请解释这个概念", sectionId=section_id)


def collect_events(response):
    return asyncio.run(_collect_events(response))


async def _collect_events(response):
    return [chunk async for chunk in response.body_iterator]


class StreamMessageLifecycleTests(unittest.TestCase):
    def test_preflight_rejects_legacy_section_mismatch_and_active_run(self):
        cases = [
            (
                None,
                "section-1",
                "Legacy course-level conversations cannot receive section messages",
            ),
            ("section-1", "section-2", "Conversation belongs to a different section"),
            ("section-1", "section-1", "该问题讨论正在处理上一条消息，请稍候"),
        ]
        for conversation_section, request_section, detail in cases:
            with self.subTest(detail=detail):
                active = (
                    AIRun(id="run-1", conversation_id="conversation-1", status="running")
                    if "上一条" in detail else None
                )
                conversation, card, section, db = make_fixture(
                    section_id=conversation_section, active_run=active
                )
                with patch("backend.conversation_api.owned_conversation"):
                    with self.assertRaises(HTTPException) as caught:
                        asyncio.run(
                            conversation_api.stream_message(
                                "conversation-1", payload(request_section), db
                            )
                        )
                self.assertEqual(caught.exception.status_code, 409)
                self.assertEqual(caught.exception.detail, detail)
                self.assertEqual(db.added, [])

    def test_normal_stream_emits_ordered_terminal_events_and_completes_run(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(
            stream_text=lambda messages, task: AsyncTextStream(["你好", "，同学"])
        )
        plan = SimpleNamespace(
            target_length="medium", intent="解释", direct_answer="答案",
            key_points=["要点"], needs_example=False,
        )
        diagnosis = SimpleNamespace(
            diagnosis=SimpleNamespace(has_knowledge_gap=False, missing_topics=[]),
            proposal=None,
        )
        agent = SimpleNamespace(name="导师", role="teacher")
        with patch("backend.conversation_api.owned_conversation"), patch(
            "backend.services.conversation_stream.get_agent", return_value=agent
        ), patch(
            "backend.services.conversation_stream.restore_active_provider",
            return_value=provider,
        ), patch("backend.services.conversation_stream.SideAgent") as side_cls, patch(
            "backend.services.conversation_stream.TeacherAgent"
        ) as teacher_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            side_cls.return_value.diagnose = AsyncMock(return_value=diagnosis)
            teacher_cls.return_value.create_side_followup = AsyncMock(
                side_effect=RuntimeError("guidance unavailable")
            )
            response = asyncio.run(
                conversation_api.stream_message("conversation-1", payload(), db)
            )
            events = collect_events(response)
        names = [chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in events]
        self.assertEqual(names[0:4], ["run.started", "message.started", "run.phase", "run.phase"])
        self.assertIn("message.delta", names)
        self.assertEqual(names[-2:], ["run.completed", "message.completed"])
        self.assertEqual(
            [item.status for item in db.added if isinstance(item, AIRun)], ["completed"]
        )
        assistants = [
            item for item in db.added
            if isinstance(item, Message) and item.role == "assistant"
        ]
        self.assertEqual([item.content for item in assistants], ["你好，同学"])

    def test_provider_failure_without_delta_fails_run_and_completes_message(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(
            stream_text=lambda messages, task: AsyncTextStream(
                error=RuntimeError("provider down")
            )
        )
        plan = SimpleNamespace(
            target_length="short", intent="解释", direct_answer="答案",
            key_points=[], needs_example=False,
        )
        agent = SimpleNamespace(name="导师", role="teacher")
        with patch("backend.conversation_api.owned_conversation"), patch(
            "backend.services.conversation_stream.get_agent", return_value=agent
        ), patch(
            "backend.services.conversation_stream.restore_active_provider",
            return_value=provider,
        ), patch("backend.services.conversation_stream.SideAgent") as side_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            response = asyncio.run(
                conversation_api.stream_message("conversation-1", payload(), db)
            )
            events = collect_events(response)
        names = [chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in events]
        self.assertEqual(names[-2:], ["run.failed", "message.completed"])
        run = next(item for item in db.added if isinstance(item, AIRun))
        self.assertEqual(
            (run.status, run.phase, run.error_message),
            ("failed", "answering", "provider down"),
        )
        self.assertFalse(
            any(isinstance(item, Message) and item.role == "assistant" for item in db.added)
        )

    def test_provider_failure_after_partial_delta_persists_partial_assistant(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(
            stream_text=lambda messages, task: AsyncTextStream(
                ["已生成部分"], RuntimeError("parser failed")
            )
        )
        plan = SimpleNamespace(
            target_length="short", intent="解释", direct_answer="答案",
            key_points=[], needs_example=False,
        )
        agent = SimpleNamespace(name="导师", role="teacher")
        with patch("backend.conversation_api.owned_conversation"), patch(
            "backend.services.conversation_stream.get_agent", return_value=agent
        ), patch(
            "backend.services.conversation_stream.restore_active_provider",
            return_value=provider,
        ), patch("backend.services.conversation_stream.SideAgent") as side_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            response = asyncio.run(conversation_api.stream_message("conversation-1", payload(), db))
            events = collect_events(response)
        self.assertEqual(
            [chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in events][-2:],
            ["run.failed", "message.completed"],
        )
        partials = [
            item for item in db.added
            if isinstance(item, Message) and item.role == "assistant"
        ]
        self.assertEqual([item.content for item in partials], ["已生成部分"])
        run = next(item for item in db.added if isinstance(item, AIRun))
        self.assertEqual(run.status, "failed")

    def test_diagnosis_failure_still_emits_terminal_events_and_keeps_run_failed(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(
            stream_text=lambda messages, task: AsyncTextStream(["完整答案"])
        )
        plan = SimpleNamespace(
            target_length="short", intent="解释", direct_answer="答案",
            key_points=[], needs_example=False,
        )
        agent = SimpleNamespace(name="导师", role="teacher")
        with patch("backend.conversation_api.owned_conversation"), patch(
            "backend.services.conversation_stream.get_agent", return_value=agent
        ), patch(
            "backend.services.conversation_stream.restore_active_provider",
            return_value=provider,
        ), patch("backend.services.conversation_stream.SideAgent") as side_cls, patch(
            "backend.services.conversation_stream.TeacherAgent"
        ) as teacher_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            side_cls.return_value.diagnose = AsyncMock(
                side_effect=RuntimeError("diagnosis unavailable")
            )
            teacher_cls.return_value.create_side_followup = AsyncMock(
                side_effect=RuntimeError("guidance unavailable")
            )
            response = asyncio.run(conversation_api.stream_message("conversation-1", payload(), db))
            events = collect_events(response)
        names = [chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in events]
        self.assertEqual(names[-3:], ["run.failed", "run.completed", "message.completed"])
        run = next(item for item in db.added if isinstance(item, AIRun))
        self.assertEqual(
            (run.status, run.phase, run.error_message),
            ("failed", "diagnosing", "diagnosis unavailable"),
        )
        failed = json.loads(events[-3].split("data: ", 1)[1])
        self.assertEqual(failed["code"], "AI_DIAGNOSIS_FAILED")

    def test_client_cancellation_persists_partial_and_failed_run_before_propagating(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(
            stream_text=lambda messages, task: AsyncTextStream(
                ["已生成部分"], asyncio.CancelledError()
            )
        )
        plan = SimpleNamespace(
            target_length="short", intent="解释", direct_answer="答案",
            key_points=[], needs_example=False,
        )
        agent = SimpleNamespace(name="导师", role="teacher")

        async def consume_until_cancelled(response):
            chunks = []
            with self.assertRaises(asyncio.CancelledError):
                async for chunk in response.body_iterator:
                    chunks.append(chunk)
            return chunks

        with patch("backend.conversation_api.owned_conversation"), patch(
            "backend.services.conversation_stream.get_agent", return_value=agent
        ), patch(
            "backend.services.conversation_stream.restore_active_provider",
            return_value=provider,
        ), patch("backend.services.conversation_stream.SideAgent") as side_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            response = asyncio.run(conversation_api.stream_message("conversation-1", payload(), db))
            chunks = asyncio.run(consume_until_cancelled(response))

        names = [chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in chunks]
        self.assertIn("message.delta", names)
        self.assertNotIn("run.failed", names)
        self.assertNotIn("run.completed", names)
        self.assertNotIn("message.completed", names)
        run = next(item for item in db.added if isinstance(item, AIRun))
        self.assertEqual((run.status, run.phase), ("failed", "answering"))
        self.assertTrue(run.error_message)
        assistant = next(
            item for item in db.added if isinstance(item, Message) and item.role == "assistant"
        )
        started = json.loads(next(
            chunk.split("data: ", 1)[1] for chunk in chunks
            if chunk.startswith("event: message.started\n")
        ))
        self.assertEqual(assistant.id, started["messageId"])
        self.assertEqual(assistant.content, "已生成部分")

    def test_success_persists_guidance_and_proposal_with_source_links(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(
            stream_text=lambda messages, task: AsyncTextStream(["完整答案"])
        )
        plan = SimpleNamespace(
            target_length="short", intent="解释", direct_answer="答案",
            key_points=[], needs_example=False,
        )
        diagnosis = SimpleNamespace(
            diagnosis=SimpleNamespace(
                has_knowledge_gap=True,
                missing_topics=["前置概念"],
                model_dump=lambda by_alias=True: {
                    "hasKnowledgeGap": True, "missingTopics": ["前置概念"],
                },
            ),
            proposal=SimpleNamespace(
                title="前置知识", reason="需要补充", relation_type="prerequisite",
                model_dump=lambda: {
                    "title": "前置知识",
                    "reason": "需要补充",
                    "relation_type": "prerequisite",
                },
            ),
        )
        agent = SimpleNamespace(name="导师", role="teacher")
        guidance_draft = SimpleNamespace(content="回到本章节的定义")
        with patch("backend.conversation_api.owned_conversation"), patch(
            "backend.services.conversation_stream.get_agent", return_value=agent
        ), patch(
            "backend.services.conversation_stream.restore_active_provider",
            return_value=provider,
        ), patch(
            "backend.services.conversation_stream.SideAgent"
        ) as side_cls, patch(
            "backend.services.conversation_stream.TeacherAgent"
        ) as teacher_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            side_cls.return_value.diagnose = AsyncMock(return_value=diagnosis)
            teacher_cls.return_value.create_side_followup = AsyncMock(
                return_value=guidance_draft
            )
            response = asyncio.run(
                conversation_api.stream_message("conversation-1", payload(), db)
            )
            events = collect_events(response)

        names = [chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in events]
        self.assertIn("guidance.updated", names)
        self.assertIn("related_card.proposed", names)

        def event_data(event_name):
            chunk = next(
                chunk for chunk in events
                if chunk.startswith(f"event: {event_name}\n")
            )
            return json.loads(chunk.split("data: ", 1)[1])

        user_message = next(
            item for item in db.added
            if isinstance(item, Message) and item.role == "user"
        )
        assistant = next(
            item for item in db.added
            if isinstance(item, Message) and item.role == "assistant"
        )
        guidance = next(item for item in db.added if isinstance(item, TeacherGuidance))
        self.assertNotEqual(user_message.id, assistant.id)
        self.assertEqual(guidance.source_question_message_id, user_message.id)
        self.assertEqual(guidance.source_answer_message_id, assistant.id)
        self.assertEqual(guidance.source_conversation_id, conversation.id)
        self.assertEqual(guidance.source_question, payload().content)
        guidance_event = event_data("guidance.updated")
        self.assertEqual(guidance_event["id"], guidance.id)
        self.assertEqual(guidance_event["content"], guidance.content)
        self.assertEqual(guidance_event["sourceQuestionMessageId"], user_message.id)
        self.assertEqual(guidance_event["sourceAnswerMessageId"], assistant.id)

        proposal = next(item for item in db.added if isinstance(item, RelatedCardProposal))
        self.assertEqual(
            (proposal.conversation_id, proposal.card_id, proposal.section_id),
            (conversation.id, card.id, section.id),
        )
        proposal_event = event_data("related_card.proposed")
        self.assertEqual(proposal_event["proposalId"], proposal.id)
        self.assertEqual(proposal_event["title"], proposal.title)
        self.assertEqual(proposal_event["reason"], proposal.reason)
        self.assertEqual(proposal_event["relationType"], proposal.relation_type)

    def test_preflight_missing_or_deleted_card_returns_404_without_writes(self):
        for status_value in ("missing", "deleted"):
            with self.subTest(status=status_value):
                conversation, card, section, db = make_fixture()
                if status_value == "deleted":
                    card.status = "deleted"
                else:
                    db.card = None
                with patch("backend.conversation_api.owned_conversation"):
                    with self.assertRaises(HTTPException) as caught:
                        asyncio.run(
                            conversation_api.stream_message("conversation-1", payload(), db)
                        )
                self.assertEqual(caught.exception.status_code, 404)
                self.assertEqual(db.added, [])

    def test_preflight_commits_user_message_and_run_before_returning_response(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(stream_text=lambda messages, task: AsyncTextStream(["回答"]))
        with patch("backend.conversation_api.owned_conversation"), patch(
            "backend.services.conversation_stream.get_agent",
            return_value=SimpleNamespace(name="导师", role="teacher"),
        ), patch(
            "backend.services.conversation_stream.restore_active_provider", return_value=provider
        ) as restore_provider:
            response = asyncio.run(conversation_api.stream_message("conversation-1", payload(), db))
        self.assertEqual([item.role for item in db.added if isinstance(item, Message)], ["user"])
        self.assertEqual(len([item for item in db.added if isinstance(item, AIRun)]), 1)
        self.assertGreaterEqual(db.commits, 1)
        restore_provider.assert_not_called()



class ConversationRetrySqliteTests(unittest.TestCase):
    """Exercise persisted turn replacement through the real SSE consumer."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.directory.name}/retry.db")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(id="owner", username="owner", password_hash="hash")
        self.space = LearningSpace(id="space", user_id="owner", title="Space", learning_goal="Goal")
        self.card = KnowledgeCard(id="card", space_id="space", title="Card", status="active")
        self.section = CardSection(id="section", card_id="card", title="Section", content_markdown="Context")
        self.conversation = Conversation(
            id="conversation", card_id="card", section_id="section",
            conversation_type="side", title="Discussion", root_question="Original topic",
            participant_ids_json='["side_tutor"]',
        )
        self.db.add_all([self.user, self.space, self.card, self.section, self.conversation])
        self.db.commit()
        self.stack = ExitStack()
        self.stack.enter_context(patch(
            "backend.services.ownership.current_user_id", return_value="owner"
        ))
        self.prompts = []
        self.streams = []

        def stream_text(messages, task):
            self.assertEqual(task, "side_answer")
            self.prompts.append([dict(message) for message in messages])
            return self.streams.pop(0)

        self.stack.enter_context(patch(
            "backend.services.conversation_stream.restore_active_provider",
            return_value=SimpleNamespace(stream_text=stream_text),
        ))
        side = self.stack.enter_context(patch("backend.services.conversation_stream.SideAgent"))
        side.return_value.plan_answer = AsyncMock(return_value=SimpleNamespace(
            target_length="short", intent="explain", direct_answer="Answer",
            key_points=[], needs_example=False,
        ))
        side.return_value.diagnose = AsyncMock(return_value=SimpleNamespace(
            diagnosis=SimpleNamespace(has_knowledge_gap=False, missing_topics=[]), proposal=None,
        ))
        teacher = self.stack.enter_context(patch("backend.services.conversation_stream.TeacherAgent"))
        teacher.return_value.create_side_followup = AsyncMock(
            return_value=SimpleNamespace(content="Return to the section")
        )

    def tearDown(self):
        self.stack.close()
        self.db.close()
        self.engine.dispose()
        self.directory.cleanup()

    def seed_failure(self, partial=True):
        timestamp = datetime.utcnow() - timedelta(seconds=60)
        self.previous_run = AIRun(
            id="previous-run", conversation_id="conversation", status="completed", phase="completed",
            created_at=timestamp, updated_at=timestamp,
        )
        self.previous_question = Message(
            id="previous-question", conversation_id="conversation", role="user", content="Previous question",
            created_at=timestamp + timedelta(microseconds=1),
        )
        self.previous_answer = Message(
            id="previous-answer", conversation_id="conversation", role="assistant", content="Previous complete answer",
            created_at=timestamp + timedelta(microseconds=2),
        )
        self.run = AIRun(
            id="failed-run", conversation_id="conversation", run_type="side_message",
            status="failed", phase="answering", error_message="upstream disconnected",
            created_at=timestamp + timedelta(seconds=1), updated_at=timestamp + timedelta(seconds=2),
        )
        self.question = Message(
            id="original-question", conversation_id="conversation", role="user", content="Original question",
            created_at=self.run.created_at + timedelta(microseconds=1),
        )
        self.partial = Message(
            id="old-partial", conversation_id="conversation", role="assistant", content="Old incomplete answer",
            created_at=self.run.created_at + timedelta(microseconds=2),
        ) if partial else None
        self.db.add_all([
            self.previous_run, self.previous_question, self.previous_answer, self.run, self.question,
        ] + ([self.partial] if self.partial else []))
        self.db.commit()

    def messages(self, db=None):
        return list((db or self.db).scalars(select(Message).order_by(Message.created_at, Message.id)))

    def latest(self, db=None):
        return conversation_api.get_latest_run("conversation", db or self.db)

    def retry(self, db=None, run_id="failed-run"):
        return asyncio.run(conversation_api.retry_run("conversation", run_id, db or self.db))

    @staticmethod
    def event(events, name):
        return json.loads(next(
            chunk.split("data: ", 1)[1] for chunk in events if chunk.startswith(f"event: {name}\n")
        ))

    def assert_previous_intact(self):
        self.assertEqual(self.db.get(Message, "previous-question").content, "Previous question")
        self.assertEqual(self.db.get(Message, "previous-answer").content, "Previous complete answer")

    def assert_rejected(self, run_id="failed-run"):
        before = [(message.id, message.content) for message in self.messages()]
        with self.assertRaises(HTTPException) as caught:
            self.retry(run_id=run_id)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual([(message.id, message.content) for message in self.messages()], before)

    def exercise_legacy_retry(self, partial):
        self.seed_failure(partial=partial)
        with Session(self.engine) as refreshed:
            state = self.latest(refreshed).model_dump(by_alias=True)
        self.assertEqual(state["id"], "failed-run")
        self.assertTrue(state["retryable"])
        self.assertEqual(state["questionMessageId"], "original-question")
        self.assertEqual(state["answerMessageId"], "old-partial" if partial else None)
        self.streams.append(AsyncTextStream(["New ", "complete answer"]))
        response = self.retry()
        # Claim and replacement happen before the provider/consumer starts.
        self.assertEqual(self.db.get(AIRun, "failed-run").status, "running")
        self.assertIsNone(self.db.get(Message, "old-partial"))
        self.assertFalse(self.latest().retryable)
        events = collect_events(response)
        started = self.event(events, "run.started")
        self.assertEqual(started["runId"], "failed-run")
        self.assertEqual(started["questionMessageId"], "original-question")
        self.assertEqual(started["replacedMessageId"], "old-partial" if partial else None)
        answer_id = self.event(events, "message.started")["messageId"]
        self.assertEqual(self.db.get(Message, answer_id).content, "New complete answer")
        self.assertEqual(len(self.messages()), 4)
        self.assertEqual([item.content for item in self.messages() if item.role == "user"],
                         ["Previous question", "Original question"])
        self.assert_previous_intact()
        self.assertNotIn("Old incomplete answer", [item["content"] for item in self.prompts[-1]])
        self.assertEqual([item["content"] for item in self.prompts[-1] if item["role"] == "user"],
                         ["Previous question", "Original question"])
        guidance = self.db.scalar(select(TeacherGuidance))
        self.assertEqual(guidance.source_question_message_id, "original-question")
        self.assertEqual(guidance.source_answer_message_id, answer_id)
        self.assertTrue(events[-1].startswith("event: message.completed\n"))
        with Session(self.engine) as refreshed:
            state = self.latest(refreshed)
            self.assertEqual((state.status, state.retryable, state.answer_message_id),
                             ("completed", False, answer_id))
        self.assert_rejected()

    def test_legacy_zero_delta_failure_retries_without_duplicate_question(self):
        self.exercise_legacy_retry(partial=False)

    def test_legacy_partial_failure_replaces_only_incomplete_answer(self):
        self.exercise_legacy_retry(partial=True)

    def test_normal_failure_repeated_retry_then_success_preserves_one_turn(self):
        self.seed_failure(partial=False)
        # Start a new turn after the older failure, then retry only this new turn.
        self.streams.append(AsyncTextStream(error=RuntimeError("zero delta")))
        response = asyncio.run(conversation_api.stream_message(
            "conversation", CreateMessageRequest(content="Newest question", sectionId="section"), self.db,
        ))
        first = collect_events(response)
        started = self.event(first, "run.started")
        run_id, question_id = started["runId"], started["questionMessageId"]
        self.assertIsNone(started["replacedMessageId"])
        failed = self.event(first, "run.failed")
        self.assertEqual((failed["runId"], failed["retryable"], failed["answerMessageId"]),
                         (run_id, True, None))
        self.assert_rejected()  # The previous failed run is no longer latest.
        self.streams.append(AsyncTextStream(["Second incomplete"], RuntimeError("disconnected again")))
        second = collect_events(self.retry(run_id=run_id))
        partial_id = self.event(second, "message.started")["messageId"]
        failed = self.event(second, "run.failed")
        self.assertEqual(failed["answerMessageId"], partial_id)
        self.assertEqual(self.db.get(Message, partial_id).content, "Second incomplete")
        self.streams.append(AsyncTextStream(["Final answer"]))
        final = collect_events(self.retry(run_id=run_id))
        self.assertEqual(self.event(final, "run.started")["replacedMessageId"], partial_id)
        self.assertIsNone(self.db.get(Message, partial_id))
        answer_id = self.event(final, "message.started")["messageId"]
        self.assertEqual(self.db.get(Message, answer_id).content, "Final answer")
        self.assertEqual(len([item for item in self.messages() if item.content == "Newest question"]), 1)
        self.assertEqual(self.db.get(Message, question_id).content, "Newest question")
        self.assertNotIn("Second incomplete", [item["content"] for item in self.prompts[-1]])
        self.assertEqual(self.db.get(AIRun, run_id).status, "completed")
        self.assert_previous_intact()

    def test_duplicate_retry_from_second_session_does_not_clear_or_create_messages(self):
        self.seed_failure()
        with Session(self.engine) as contender:
            contender.get(AIRun, "failed-run")  # An independently loaded refresh/request.
            self.retry()
            with self.assertRaises(HTTPException) as caught:
                self.retry(contender)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual([item.id for item in self.messages(contender)],
                             ["previous-question", "previous-answer", "original-question"])
        self.assertEqual(self.db.get(AIRun, "failed-run").status, "running")

    def test_conditional_claim_rejects_contender_after_both_read_failed_state(self):
        self.seed_failure()
        winner = ConversationStreamService(self.db)
        contexts = []

        class ContenderService(ConversationStreamService):
            def run_response(inner, conversation, run):
                state = super().run_response(conversation, run)
                # Deterministically interleave the competing database claim
                # after eligibility is read but before this request claims it.
                contexts.append(winner.prepare_retry(self.conversation, self.card, run.id))
                return state

        with Session(self.engine) as contender:
            service = ContenderService(contender)
            with self.assertRaises(HTTPException) as caught:
                service.prepare_retry(
                    contender.get(Conversation, "conversation"),
                    contender.get(KnowledgeCard, "card"), "failed-run",
                )
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(caught.exception.detail, "该轮回答正在处理或不可重试")
        self.assertEqual(len(self.messages()), 3)
        self.assertEqual(self.run.status, "running")
        self.streams.append(AsyncTextStream(["Winner answer"]))
        events = collect_events(SimpleNamespace(body_iterator=winner.events(contexts[0])))
        answer_id = self.event(events, "message.started")["messageId"]
        self.assertEqual(self.db.get(Message, answer_id).content, "Winner answer")
        self.assertEqual(len(self.messages()), 4)
        self.assert_previous_intact()

    def test_consumer_task_cancellation_saves_partial_and_latest_state(self):
        self.seed_failure(partial=False)

        async def consume_and_cancel():
            waiting = asyncio.Event()

            async def upstream():
                yield "Interrupted partial"
                waiting.set()
                await asyncio.Event().wait()

            self.streams.append(upstream())
            response = await conversation_api.retry_run("conversation", "failed-run", self.db)
            chunks = []

            async def consume():
                async for chunk in response.body_iterator:
                    chunks.append(chunk)

            task = asyncio.create_task(consume())
            await waiting.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            return chunks

        chunks = asyncio.run(consume_and_cancel())
        answer_id = self.event(chunks, "message.started")["messageId"]
        self.assertEqual(self.db.get(Message, answer_id).content, "Interrupted partial")
        self.assertFalse(any(chunk.startswith("event: message.completed\n") for chunk in chunks))
        with Session(self.engine) as refreshed:
            state = self.latest(refreshed)
            self.assertEqual((state.status, state.phase, state.retryable), ("failed", "answering", True))
            self.assertEqual(state.answer_message_id, answer_id)
        self.streams.append(AsyncTextStream(["Recovered answer"]))
        events = collect_events(self.retry())
        self.assertEqual(self.event(events, "run.started")["replacedMessageId"], answer_id)
        self.assertEqual(len(self.messages()), 4)
        self.assert_previous_intact()

    def test_zero_delta_cancellation_keeps_question_and_is_retryable_after_refresh(self):
        self.seed_failure(partial=False)
        self.streams.append(AsyncTextStream(error=asyncio.CancelledError()))
        response = self.retry()

        async def consume():
            with self.assertRaises(asyncio.CancelledError):
                async for _chunk in response.body_iterator:
                    pass

        asyncio.run(consume())
        self.assertEqual(len(self.messages()), 3)
        with Session(self.engine) as refreshed:
            state = self.latest(refreshed)
            self.assertEqual((state.status, state.retryable, state.answer_message_id),
                             ("failed", True, None))
            self.assertEqual(state.question_message_id, "original-question")
        self.streams.append(AsyncTextStream(["Recovered without duplicated user"]))
        collect_events(self.retry())
        self.assertEqual(len(self.messages()), 4)
        self.assert_previous_intact()

    def test_expired_answering_partial_accepts_retry_without_losing_interrupted_phase(self):
        self.seed_failure()
        self.run.status = "running"
        self.run.updated_at = datetime(2026, 1, 1)
        self.db.commit()
        self.streams.append(AsyncTextStream(["Recovered expired answer"]))
        with patch("backend.services.conversation_stream.now", return_value=datetime(2026, 1, 2)):
            state = self.latest()
            self.assertEqual((state.status, state.phase, state.retryable),
                             ("expired", "answering", True))
            response = self.retry()
        events = collect_events(response)
        self.assertEqual(self.event(events, "run.started")["replacedMessageId"], "old-partial")
        self.assertEqual(self.run.status, "completed")
        self.assertEqual(len(self.messages()), 4)
        self.assert_previous_intact()

    def test_expiry_preserves_phase_and_never_retries_complete_answer_diagnosis(self):
        self.seed_failure(partial=False)
        for phase, retryable in (("waiting", True), ("planning", True), ("answering", True),
                                 ("guiding", False), ("diagnosing", False)):
            with self.subTest(phase=phase):
                self.run.status, self.run.phase = "running", phase
                self.run.updated_at = datetime(2026, 1, 1)
                self.db.commit()
                with patch("backend.services.conversation_stream.now", return_value=datetime(2026, 1, 2)):
                    state = self.latest()
                self.assertEqual((state.status, state.phase, state.retryable), ("expired", phase, retryable))

    def test_cross_user_latest_and_retry_are_not_found_and_leave_partial_intact(self):
        self.seed_failure()
        with patch("backend.services.ownership.current_user_id", return_value="other-user"):
            for call in (self.latest, self.retry):
                with self.subTest(call=call.__name__), self.assertRaises(HTTPException) as caught:
                    call()
                self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.db.get(Message, "old-partial").content, "Old incomplete answer")
        self.assertEqual(self.run.status, "failed")

    def test_rejects_nonretryable_run_states_and_missing_run(self):
        self.seed_failure()
        self.assert_rejected("missing")
        self.assert_rejected("previous-run")
        for status, phase, run_type in (
            ("completed", "completed", "side_message"), ("failed", "diagnosing", "side_message"),
            ("failed", "guiding", "side_message"), ("failed", "answering", "other"),
            ("running", "answering", "side_message"), ("failed", "planning", "side_message"),
        ):
            with self.subTest(status=status, phase=phase, run_type=run_type):
                self.run.status, self.run.phase, self.run.run_type = status, phase, run_type
                self.db.commit()
                self.assertFalse(self.latest().retryable)
                self.assert_rejected()

    def test_rejects_missing_original_question_instead_of_using_previous_turn(self):
        self.seed_failure(partial=False)
        self.db.delete(self.question)
        self.db.commit()
        self.assertIsNone(self.latest().question_message_id)
        self.assert_rejected()
        self.assert_previous_intact()

    def test_rejects_malformed_turn_with_additional_question_or_answer(self):
        self.seed_failure()
        for role in ("user", "assistant"):
            with self.subTest(role=role):
                extra = Message(
                    id="extra", conversation_id="conversation", role=role, content="Unexpected",
                    created_at=self.run.created_at + timedelta(seconds=3),
                )
                self.db.add(extra)
                self.db.commit()
                self.assertFalse(self.latest().retryable)
                self.assert_rejected()
                self.db.delete(extra)
                self.db.commit()

    def test_rejects_invalid_section_and_other_active_run(self):
        self.seed_failure()
        self.conversation.section_id = None
        self.db.commit()
        self.assert_rejected()
        self.conversation.section_id = "missing"
        self.db.commit()
        self.assert_rejected()
        self.conversation.section_id = "section"
        self.previous_run.status = "running"
        self.db.commit()
        self.assertFalse(self.latest().retryable)
        self.assert_rejected()

    def test_rejects_foreign_section_and_ambiguous_run_chronology(self):
        self.seed_failure()
        foreign_card = KnowledgeCard(id="foreign-card", space_id="space", title="Foreign card")
        foreign_section = CardSection(id="foreign-section", card_id="foreign-card", title="Foreign")
        self.db.add_all([foreign_card, foreign_section])
        self.conversation.section_id = "foreign-section"
        self.db.commit()
        self.assertFalse(self.latest().retryable)
        self.assert_rejected()
        self.conversation.section_id = "section"
        self.previous_run.created_at = self.run.created_at
        self.db.commit()
        self.assertFalse(self.latest().retryable)
        self.assert_rejected()

    def test_complete_answer_guidance_link_prevents_destructive_retry_with_stale_phase(self):
        self.seed_failure()
        self.db.add(TeacherGuidance(
            card_id="card", section_id="section", source_conversation_id="conversation",
            source_question_message_id="original-question", source_answer_message_id="old-partial",
            trigger="side_question", content="This answer already reached guidance",
        ))
        self.db.commit()
        self.assertFalse(self.latest().retryable)
        self.assert_rejected()

    def test_latest_without_runs_is_null(self):
        self.assertIsNone(self.latest())


class SseEncodingTests(unittest.TestCase):
    def test_encode_event_preserves_unicode_and_escapes_newlines_in_json(self):
        encoded = encode_event(
            "message.delta", {"delta": "第一行\n第二行", "label": "答疑"}
        )
        self.assertEqual(encoded.splitlines()[0], "event: message.delta")
        body = encoded.split("data: ", 1)[1].strip()
        self.assertEqual(json.loads(body), {"delta": "第一行\n第二行", "label": "答疑"})


if __name__ == "__main__":
    unittest.main()
