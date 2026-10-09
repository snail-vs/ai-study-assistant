import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from ..agents.prompts import QA_TUTOR_SYSTEM
from ..agents.registry import get_agent
from ..agents.side_agent import SideAgent
from ..agents.teacher_agent import TeacherAgent
from ..models import (
    AIRun,
    CardSection,
    Conversation,
    KnowledgeCard,
    Message,
    RelatedCardProposal,
    TeacherGuidance,
    now,
)
from ..schemas import AIRunResponse, CreateMessageRequest, TeacherGuidanceResponse
from ..services.provider_settings import restore_active_provider
from ..sse import encode_event

logger = logging.getLogger("studycenter.api")


@dataclass
class StreamContext:
    conversation: Conversation
    card: KnowledgeCard
    payload: CreateMessageRequest
    user_message: Message
    run: AIRun
    primary_agent_id: str
    primary_agent: object | None
    replaced_message_id: str | None = None


class ConversationStreamService:
    def __init__(self, db: Session):
        self.db = db

    def latest_run(self, conversation_id: str) -> AIRun | None:
        run = self.db.scalar(
            select(AIRun)
            .where(AIRun.conversation_id == conversation_id)
            .order_by(AIRun.created_at.desc(), AIRun.id.desc())
            .limit(1)
        )
        if (
            run and run.status in ("queued", "running") and run.updated_at
            and (now() - run.updated_at).total_seconds() > 180
        ):
            run.status = "expired"
            # Keep the interrupted phase: an expired diagnosis has a complete answer.
            run.error_message = "AI 请求可能已中断。"
            self.db.commit()
        return run

    def latest_turn(self, run: AIRun) -> tuple[Message | None, Message | None]:
        if run.run_type != "side_message" or not run.created_at:
            return None, None
        ambiguous = self.db.scalar(select(AIRun.id).where(
            AIRun.conversation_id == run.conversation_id,
            AIRun.id != run.id, AIRun.created_at == run.created_at,
        ).limit(1))
        if ambiguous:
            return None, None
        # SQLAlchemy inserts the run just before its user message. Do not attach
        # the preceding completed question to a legacy run with no new question.
        turn = list(self.db.scalars(
            select(Message)
            .where(
                Message.conversation_id == run.conversation_id,
                Message.created_at >= run.created_at,
            )
            .order_by(Message.created_at, Message.id)
        ))
        if not turn or len(turn) > 2:
            return None, None
        question = turn[0]
        if (
            question.role != "user" or question.visibility != "user"
            or not question.content.strip() or question.created_at <= run.created_at
        ):
            return None, None
        answer = turn[1] if len(turn) == 2 else None
        if answer and (
            answer.role != "assistant" or answer.visibility != "user"
            or answer.created_at <= question.created_at
        ):
            return None, None
        return question, answer

    def run_response(self, conversation: Conversation, run: AIRun) -> AIRunResponse:
        question, answer = self.latest_turn(run)
        section = self.db.get(CardSection, conversation.section_id) if conversation.section_id else None
        active = self.db.scalar(select(AIRun.id).where(
            AIRun.conversation_id == conversation.id,
            AIRun.status.in_(("queued", "running")),
        ).limit(1))
        guidance = self.db.scalar(select(TeacherGuidance.id).where(
            TeacherGuidance.source_question_message_id == question.id,
        ).limit(1)) if question else None
        response = AIRunResponse.model_validate(run)
        response.question_message_id = question.id if question else None
        response.answer_message_id = answer.id if answer else None
        response.retryable = bool(
            run.run_type == "side_message" and run.status in ("failed", "expired")
            and run.phase in ("waiting", "planning", "answering")
            and question and section and section.card_id == conversation.card_id
            and (not answer or run.phase == "answering")
            and not active and not guidance
        )
        return response

    def prepare_retry(
        self, conversation: Conversation, card: KnowledgeCard, run_id: str,
    ) -> StreamContext:
        run = self.latest_run(conversation.id)
        if not run or run.id != run_id or not self.run_response(conversation, run).retryable:
            raise HTTPException(status_code=409, detail="该轮回答不可重试")
        question, answer = self.latest_turn(run)
        other = aliased(AIRun)
        # The database claim, not the preflight read, decides who may regenerate.
        claimed = self.db.execute(
            update(AIRun).where(
                AIRun.id == run.id,
                AIRun.status.in_(("failed", "expired")),
                AIRun.phase.in_(("waiting", "planning", "answering")),
                ~exists(select(other.id).where(
                    other.conversation_id == conversation.id,
                    or_(
                        other.status.in_(("queued", "running")),
                        other.created_at > run.created_at,
                        (other.created_at == run.created_at) & (other.id > run.id),
                    ),
                )),
            ).values(status="running", phase="waiting", error_message=None, updated_at=now()),
            execution_options={"synchronize_session": False},
        )
        if claimed.rowcount != 1:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="该轮回答正在处理或不可重试")
        replaced_message_id = answer.id if answer else None
        if answer:
            self.db.delete(answer)
        self.db.commit()
        self.db.refresh(run)
        payload = CreateMessageRequest(content=question.content, sectionId=conversation.section_id)
        return self._context(conversation, card, payload, question, run, replaced_message_id)

    def prepare(
        self,
        conversation: Conversation,
        card: KnowledgeCard,
        payload: CreateMessageRequest,
    ) -> StreamContext:
        # Explicit creation order also makes new turns unambiguous on refresh.
        run = AIRun(
            conversation_id=conversation.id,
            run_type="side_message",
            status="running",
            phase="waiting",
        )
        self.db.add(run)
        self.db.flush()
        user_message = Message(
            conversation_id=conversation.id,
            role="user",
            sender_id="user",
            sender_name="你",
            sender_role="user",
            visibility="user",
            content=payload.content,
        )
        self.db.add(user_message)
        self.db.commit()
        return self._context(conversation, card, payload, user_message, run)

    def _context(
        self, conversation: Conversation, card: KnowledgeCard,
        payload: CreateMessageRequest, user_message: Message, run: AIRun,
        replaced_message_id: str | None = None,
    ) -> StreamContext:
        primary_agent_id = conversation.participant_ids[0] if conversation.participant_ids else (
            "teacher" if conversation.conversation_type == "main" else "side_tutor"
        )
        return StreamContext(
            conversation=conversation, card=card, payload=payload,
            user_message=user_message, run=run,
            primary_agent_id=primary_agent_id, primary_agent=get_agent(primary_agent_id),
            replaced_message_id=replaced_message_id,
        )

    async def events(self, context: StreamContext) -> AsyncIterator[str]:
        db = self.db
        conversation = context.conversation
        card = context.card
        payload = context.payload
        run = context.run
        user_message = context.user_message
        primary_agent_id = context.primary_agent_id
        primary_agent = context.primary_agent
        message_id = str(uuid4())
        yield encode_event(
            "run.started",
            {
                "conversationId": conversation.id,
                "runId": run.id,
                "questionMessageId": user_message.id,
                "replacedMessageId": context.replaced_message_id,
                "phase": "waiting",
                "label": "正在等待 AI 响应",
            },
        )
        yield encode_event(
            "message.started",
            {
                "conversationId": conversation.id,
                "messageId": message_id,
                "senderId": primary_agent_id,
                "senderName": primary_agent.name if primary_agent else primary_agent_id,
                "senderRole": primary_agent.role if primary_agent else "assistant",
            },
        )
        answer_section = (
            db.get(CardSection, conversation.section_id) if conversation.section_id else None
        )
        messages = [{"role": "system", "content": QA_TUTOR_SYSTEM}]
        answer_context = ""
        if answer_section:
            answer_context = (
                f"当前知识卡：{card.title}\n当前章节：{answer_section.title}\n"
                f"课程内容：{answer_section.content_markdown[:6000]}"
            )
            messages.append({"role": "system", "content": answer_context})
        try:
            yield encode_event(
                "run.phase", {"phase": "planning", "label": "正在理解问题并组织回答"}
            )
            run.phase = "planning"
            db.commit()
            answer_plan = await SideAgent(restore_active_provider(db)).plan_answer(
                payload.content,
                context=answer_context,
            )
            length_budget = {
                "short": "80～200",
                "medium": "200～400",
                "long": "400～700",
            }[answer_plan.target_length]
            messages.append({
                "role": "system",
                "content": (
                    "请严格依据下面的回答计划作答，不要扩展计划之外的"
                    "背景知识。\n"
                    f"回答类型：{answer_plan.intent}\n"
                    f"直接答案：{answer_plan.direct_answer}\n"
                    f"必要要点：{json.dumps(answer_plan.key_points, ensure_ascii=False)}\n"
                    f"是否需要例子：{'是' if answer_plan.needs_example else '否'}\n"
                    f"目标长度：{length_budget} 个中文字符。"
                ),
            })
        except Exception:
            logger.exception("side answer planning failed; falling back to direct answer")
        yield encode_event("run.phase", {"phase": "answering", "label": "答疑助教正在回答"})
        run.phase = "answering"
        db.commit()
        if conversation.root_question:
            messages.append({
                "role": "system",
                "content": f"本讨论的起始问题：{conversation.root_question}",
            })
        history = list(db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.visibility == "user")
            .order_by(Message.created_at, Message.id)
        ))[-8:]
        messages.extend({"role": item.role, "content": item.content} for item in history)
        response_parts: list[str] = []
        try:
            async for delta in restore_active_provider(db).stream_text(
                messages, task="side_answer"
            ):
                response_parts.append(delta)
                yield encode_event(
                    "message.delta",
                    {"messageId": message_id, "senderId": primary_agent_id, "delta": delta},
                )
        except (Exception, asyncio.CancelledError) as exc:
            if response_parts:
                db.add(Message(
                    id=message_id,
                    conversation_id=conversation.id,
                    role="assistant",
                    sender_id=primary_agent_id,
                    sender_name=primary_agent.name if primary_agent else primary_agent_id,
                    sender_role=primary_agent.role if primary_agent else "assistant",
                    visibility="user",
                    content="".join(response_parts),
                ))
            run.status = "failed"
            run.phase = "answering"
            run.error_message = str(exc) or "AI 回答已中断"
            db.commit()
            if isinstance(exc, asyncio.CancelledError):
                raise
            message = str(exc)
            if "MissingSessionID" in message or "only be used in OpenCode" in message:
                message = (
                    "OpenCode 免费模型只能在 OpenCode 会话中使用，请改用"
                    " OpenCode 付费模型、"
                    "DeepSeek 或 OpenRouter 模型。"
                )
            yield encode_event("run.failed", {
                "code": "AI_PROVIDER_ERROR", "message": message,
                "runId": run.id, "phase": run.phase, "retryable": True,
                "questionMessageId": user_message.id,
                "answerMessageId": message_id if response_parts else None,
            })
            yield "event: message.completed\ndata: {}\n\n"
            return
        assistant = Message(
            id=message_id,
            conversation_id=conversation.id,
            role="assistant",
            sender_id=primary_agent_id,
            sender_name=primary_agent.name if primary_agent else primary_agent_id,
            sender_role=primary_agent.role if primary_agent else "assistant",
            visibility="user",
            content="".join(response_parts),
        )
        db.add(assistant)
        db.commit()
        try:
            section = (
                db.get(CardSection, conversation.section_id) if conversation.section_id else None
            )
            source_card = db.get(KnowledgeCard, conversation.card_id) if section else None
            if not section or not source_card or section.card_id != conversation.card_id:
                logger.warning(
                    "skip teacher guidance: conversation_id=%s card_id=%s "
                    "conversation_section_id=%s payload_section_id=%s",
                    conversation.id,
                    conversation.card_id,
                    conversation.section_id,
                    payload.section_id,
                )
            if section and source_card and section.card_id == conversation.card_id:
                try:
                    yield encode_event(
                        "run.phase", {"phase": "guiding", "label": "课程导师正在引导归位"}
                    )
                    run.phase = "guiding"
                    db.commit()
                    guidance_draft = await TeacherAgent(
                        restore_active_provider(db)
                    ).create_side_followup(
                        source_card.title,
                        section.title,
                        section.content_markdown,
                        payload.content,
                        "".join(response_parts),
                    )
                    guidance = TeacherGuidance(
                        card_id=conversation.card_id,
                        section_id=section.id,
                        source_conversation_id=conversation.id,
                        source_question_message_id=user_message.id,
                        source_answer_message_id=assistant.id,
                        source_question=payload.content,
                        trigger="side_question",
                        content=guidance_draft.content,
                    )
                    db.add(guidance)
                    db.commit()
                    db.refresh(guidance)
                    yield encode_event(
                        "guidance.updated",
                        TeacherGuidanceResponse.model_validate(guidance).model_dump(by_alias=True),
                        default=str,
                    )
                except Exception as exc:
                    logger.exception(
                        "teacher guidance failed: conversation_id=%s card_id=%s section_id=%s",
                        conversation.id,
                        conversation.card_id,
                        section.id,
                    )
                    yield encode_event(
                        "guidance.failed",
                        {"code": "TEACHER_GUIDANCE_FAILED", "message": str(exc)},
                    )
            yield encode_event(
                "run.phase", {"phase": "diagnosing", "label": "正在分析你的知识断层"}
            )
            run.phase = "diagnosing"
            db.commit()
            diagnosis = await SideAgent(restore_active_provider(db)).diagnose(
                payload.content,
                context=(
                    f"知识卡：{source_card.title}\n章节：{section.title}\n"
                    f"课程内容：{section.content_markdown}"
                    if section and source_card else ""
                ),
            )
            logger.info(
                "side-agent diagnosis: conversation_id=%s has_knowledge_gap=%s "
                "missing_topics=%s proposal=%s",
                conversation.id,
                diagnosis.diagnosis.has_knowledge_gap,
                diagnosis.diagnosis.missing_topics,
                diagnosis.proposal.title if diagnosis.proposal else None,
            )
            if diagnosis.diagnosis.has_knowledge_gap or diagnosis.proposal:
                yield encode_event(
                    "diagnosis.updated", diagnosis.diagnosis.model_dump(by_alias=True)
                )
                if diagnosis.proposal:
                    yield encode_event(
                        "run.phase",
                        {"phase": "recommending", "label": "正在整理相关学习建议"},
                    )
                    proposal = diagnosis.proposal.model_dump()
                    stored = RelatedCardProposal(
                        conversation_id=conversation.id,
                        card_id=conversation.card_id,
                        section_id=conversation.section_id,
                        title=proposal["title"],
                        reason=proposal["reason"],
                        relation_type=proposal["relation_type"],
                    )
                    db.add(stored)
                    db.commit()
                    proposal["proposalId"] = stored.id
                    proposal["relationType"] = proposal.pop("relation_type")
                    yield encode_event("related_card.proposed", proposal)
        except Exception as exc:
            run.status = "failed"
            run.phase = "diagnosing"
            run.error_message = str(exc)
            db.commit()
            yield encode_event(
                "run.failed",
                {
                    "code": "AI_DIAGNOSIS_FAILED", "message": str(exc),
                    "runId": run.id, "phase": run.phase, "retryable": False,
                    "questionMessageId": user_message.id, "answerMessageId": assistant.id,
                },
                ensure_ascii=True,
            )
        if run.status != "failed":
            run.status = "completed"
            run.phase = "completed"
            db.commit()
        yield encode_event("run.completed", {"conversationId": conversation.id})
        yield "event: message.completed\ndata: {}\n\n"
