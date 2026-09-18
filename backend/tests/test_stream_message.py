import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend import api
from backend.models import AIRun, CardSection, Conversation, KnowledgeCard, Message
from backend.schemas import CreateMessageRequest


class SessionDouble:
    """Small unit-test seam for the streaming route's session contract."""

    def __init__(self, conversation, card, section=None, active_run=None):
        self.conversation = conversation
        self.card = card
        self.section = section
        self.active_run = active_run
        self.added = []
        self.commits = 0

    def get(self, model, identifier):
        values = {
            (Conversation, self.conversation.id): self.conversation,
            (KnowledgeCard, self.card.id): self.card,
            (CardSection, self.section.id if self.section else None): self.section,
        }
        return values.get((model, identifier))

    def scalar(self, _statement):
        return self.active_run

    def scalars(self, _statement):
        return iter([item for item in self.added if isinstance(item, Message) and item.role == "user"])

    def add(self, value):
        if isinstance(value, (Message, AIRun)) and not value.id:
            value.id = f"{value.__class__.__name__.lower()}-test"
        self.added.append(value)

    def commit(self):
        self.commits += 1

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
    section = CardSection(id="section-1", card_id="card-1", title="章节", content_markdown="内容")
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
            (None, "section-1", "Legacy course-level conversations cannot receive section messages"),
            ("section-1", "section-2", "Conversation belongs to a different section"),
            ("section-1", "section-1", "该问题讨论正在处理上一条消息，请稍候"),
        ]
        for conversation_section, request_section, detail in cases:
            with self.subTest(detail=detail):
                active = AIRun(id="run-1", conversation_id="conversation-1", status="running") if "上一条" in detail else None
                conversation, card, section, db = make_fixture(section_id=conversation_section, active_run=active)
                with patch("backend.api.owned_conversation"), patch("backend.api.current_user_id", return_value="user-1"):
                    with self.assertRaises(HTTPException) as caught:
                        asyncio.run(api.stream_message("conversation-1", payload(request_section), db))
                self.assertEqual(caught.exception.status_code, 409)
                self.assertEqual(caught.exception.detail, detail)
                self.assertEqual(db.added, [])

    def test_normal_stream_emits_ordered_terminal_events_and_completes_run(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(stream_text=lambda messages, task: AsyncTextStream(["你好", "，同学"]))
        plan = SimpleNamespace(target_length="medium", intent="解释", direct_answer="答案", key_points=["要点"], needs_example=False)
        diagnosis = SimpleNamespace(diagnosis=SimpleNamespace(has_knowledge_gap=False, missing_topics=[]), proposal=None)
        agent = SimpleNamespace(name="导师", role="teacher")
        with patch("backend.api.owned_conversation"), patch("backend.api.get_agent", return_value=agent), \
                patch("backend.api.restore_active_provider", return_value=provider), \
                patch("backend.api.SideAgent") as side_cls, patch("backend.api.TeacherAgent") as teacher_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            side_cls.return_value.diagnose = AsyncMock(return_value=diagnosis)
            teacher_cls.return_value.create_side_followup = AsyncMock(side_effect=RuntimeError("guidance unavailable"))
            response = asyncio.run(api.stream_message("conversation-1", payload(), db))
            events = collect_events(response)
        names = [chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in events]
        self.assertEqual(names[0:4], ["run.started", "message.started", "run.phase", "run.phase"])
        self.assertIn("message.delta", names)
        self.assertEqual(names[-2:], ["run.completed", "message.completed"])
        self.assertEqual([item.status for item in db.added if isinstance(item, AIRun)], ["completed"])
        assistants = [item for item in db.added if isinstance(item, Message) and item.role == "assistant"]
        self.assertEqual([item.content for item in assistants], ["你好，同学"])

    def test_provider_failure_without_delta_fails_run_and_completes_message(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(stream_text=lambda messages, task: AsyncTextStream(error=RuntimeError("provider down")))
        plan = SimpleNamespace(target_length="short", intent="解释", direct_answer="答案", key_points=[], needs_example=False)
        agent = SimpleNamespace(name="导师", role="teacher")
        with patch("backend.api.owned_conversation"), patch("backend.api.get_agent", return_value=agent), \
                patch("backend.api.restore_active_provider", return_value=provider), patch("backend.api.SideAgent") as side_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            response = asyncio.run(api.stream_message("conversation-1", payload(), db))
            events = collect_events(response)
        names = [chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in events]
        self.assertEqual(names[-2:], ["run.failed", "message.completed"])
        run = next(item for item in db.added if isinstance(item, AIRun))
        self.assertEqual((run.status, run.phase, run.error_message), ("failed", "answering", "provider down"))
        self.assertFalse(any(isinstance(item, Message) and item.role == "assistant" for item in db.added))

    def test_provider_failure_after_partial_delta_persists_partial_assistant(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(stream_text=lambda messages, task: AsyncTextStream(["已生成部分"], RuntimeError("parser failed")))
        plan = SimpleNamespace(target_length="short", intent="解释", direct_answer="答案", key_points=[], needs_example=False)
        agent = SimpleNamespace(name="导师", role="teacher")
        with patch("backend.api.owned_conversation"), patch("backend.api.get_agent", return_value=agent), \
                patch("backend.api.restore_active_provider", return_value=provider), patch("backend.api.SideAgent") as side_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            response = asyncio.run(api.stream_message("conversation-1", payload(), db))
            events = collect_events(response)
        self.assertEqual([chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in events][-2:], ["run.failed", "message.completed"])
        partials = [item for item in db.added if isinstance(item, Message) and item.role == "assistant"]
        self.assertEqual([item.content for item in partials], ["已生成部分"])
        run = next(item for item in db.added if isinstance(item, AIRun))
        self.assertEqual(run.status, "failed")

    def test_diagnosis_failure_still_emits_terminal_events_and_keeps_run_failed(self):
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(stream_text=lambda messages, task: AsyncTextStream(["完整答案"]))
        plan = SimpleNamespace(target_length="short", intent="解释", direct_answer="答案", key_points=[], needs_example=False)
        agent = SimpleNamespace(name="导师", role="teacher")
        with patch("backend.api.owned_conversation"), patch("backend.api.get_agent", return_value=agent), \
                patch("backend.api.restore_active_provider", return_value=provider), patch("backend.api.SideAgent") as side_cls, \
                patch("backend.api.TeacherAgent") as teacher_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            side_cls.return_value.diagnose = AsyncMock(side_effect=RuntimeError("diagnosis unavailable"))
            teacher_cls.return_value.create_side_followup = AsyncMock(side_effect=RuntimeError("guidance unavailable"))
            response = asyncio.run(api.stream_message("conversation-1", payload(), db))
            events = collect_events(response)
        names = [chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in events]
        self.assertEqual(names[-3:], ["run.failed", "run.completed", "message.completed"])
        run = next(item for item in db.added if isinstance(item, AIRun))
        self.assertEqual((run.status, run.phase, run.error_message), ("failed", "diagnosing", "diagnosis unavailable"))
        failed = json.loads(events[-3].split("data: ", 1)[1])
        self.assertEqual(failed["code"], "AI_DIAGNOSIS_FAILED")

    def test_current_behavior_client_cancellation_propagates_without_cleanup(self):
        """Characterize the current cancellation seam before streaming cleanup is refactored."""
        conversation, card, section, db = make_fixture()
        provider = SimpleNamespace(
            stream_text=lambda messages, task: AsyncTextStream(["已生成部分"], asyncio.CancelledError())
        )
        plan = SimpleNamespace(target_length="short", intent="解释", direct_answer="答案", key_points=[], needs_example=False)
        agent = SimpleNamespace(name="导师", role="teacher")

        async def consume_until_cancelled(response):
            chunks = []
            with self.assertRaises(asyncio.CancelledError):
                async for chunk in response.body_iterator:
                    chunks.append(chunk)
            return chunks

        with patch("backend.api.owned_conversation"), patch("backend.api.get_agent", return_value=agent), \
                patch("backend.api.restore_active_provider", return_value=provider), patch("backend.api.SideAgent") as side_cls:
            side_cls.return_value.plan_answer = AsyncMock(return_value=plan)
            response = asyncio.run(api.stream_message("conversation-1", payload(), db))
            chunks = asyncio.run(consume_until_cancelled(response))

        names = [chunk.split("\n", 1)[0].removeprefix("event: ") for chunk in chunks]
        self.assertIn("message.delta", names)
        self.assertNotIn("run.failed", names)
        self.assertNotIn("run.completed", names)
        self.assertNotIn("message.completed", names)
        run = next(item for item in db.added if isinstance(item, AIRun))
        self.assertEqual((run.status, run.phase, run.error_message), ("running", "answering", None))
        self.assertFalse(any(isinstance(item, Message) and item.role == "assistant" for item in db.added))


if __name__ == "__main__":
    unittest.main()
