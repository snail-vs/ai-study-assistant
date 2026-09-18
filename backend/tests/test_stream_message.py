import asyncio
import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend import conversation_api
from backend.models import (
    AIRun,
    CardSection,
    Conversation,
    KnowledgeCard,
    Message,
    RelatedCardProposal,
    TeacherGuidance,
)
from backend.schemas import CreateMessageRequest
from backend.sse import encode_event


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

    def test_current_behavior_client_cancellation_propagates_without_cleanup(self):
        """Characterize the current cancellation seam before streaming cleanup is refactored."""
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
        self.assertEqual((run.status, run.phase, run.error_message), ("running", "answering", None))
        self.assertFalse(
            any(isinstance(item, Message) and item.role == "assistant" for item in db.added)
        )

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

    def test_active_run_expires_after_180_seconds_but_fresh_run_remains_running(self):
        from datetime import timedelta

        for age_seconds, expected_status in ((181, "expired"), (179, "running")):
            with self.subTest(age_seconds=age_seconds):
                run = AIRun(
                    id="run-1", conversation_id="conversation-1", status="running",
                    phase="answering",
                    created_at=datetime.utcnow() - timedelta(seconds=age_seconds),
                    updated_at=datetime.utcnow() - timedelta(seconds=age_seconds),
                )
                db = MagicMock()
                db.scalar.return_value = run
                with patch("backend.conversation_api.owned_conversation"), patch(
                    "backend.conversation_api.now", return_value=datetime.utcnow()
                ):
                    result = conversation_api.get_active_run("conversation-1", db)
                self.assertIs(result, run)
                self.assertEqual(run.status, expected_status)
                if expected_status == "expired":
                    db.commit.assert_called_once()
                else:
                    db.commit.assert_not_called()


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
