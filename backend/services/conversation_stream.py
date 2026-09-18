import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator
from uuid import uuid4

from sqlalchemy import select
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
)
from ..schemas import CreateMessageRequest, TeacherGuidanceResponse
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


class ConversationStreamService:
    def __init__(self, db: Session):
        self.db = db

    def prepare(
        self,
        conversation: Conversation,
        card: KnowledgeCard,
        payload: CreateMessageRequest,
    ) -> StreamContext:
        primary_agent_id = conversation.participant_ids[0] if conversation.participant_ids else (
            "teacher" if conversation.conversation_type == "main" else "side_tutor"
        )
        primary_agent = get_agent(primary_agent_id)
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
        run = AIRun(
            conversation_id=conversation.id,
            run_type="side_message",
            status="running",
            phase="waiting",
        )
        self.db.add(run)
        self.db.commit()
        return StreamContext(
            conversation=conversation,
            card=card,
            payload=payload,
            user_message=user_message,
            run=run,
            primary_agent_id=primary_agent_id,
            primary_agent=primary_agent,
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
        except Exception as exc:
            if response_parts:
                db.add(Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    sender_id=primary_agent_id,
                    sender_name=primary_agent.name if primary_agent else primary_agent_id,
                    sender_role=primary_agent.role if primary_agent else "assistant",
                    visibility="user",
                    content="".join(response_parts),
                ))
                db.commit()
            run.status = "failed"
            run.phase = "answering"
            run.error_message = str(exc)
            db.commit()
            message = str(exc)
            if "MissingSessionID" in message or "only be used in OpenCode" in message:
                message = (
                    "OpenCode 免费模型只能在 OpenCode 会话中使用，请改用"
                    " OpenCode 付费模型、"
                    "DeepSeek 或 OpenRouter 模型。"
                )
            yield encode_event("run.failed", {"code": "AI_PROVIDER_ERROR", "message": message})
            yield "event: message.completed\ndata: {}\n\n"
            return
        assistant = Message(
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
                {"code": "AI_DIAGNOSIS_FAILED", "message": str(exc)},
                ensure_ascii=True,
            )
        if run.status != "failed":
            run.status = "completed"
            run.phase = "completed"
            db.commit()
        yield encode_event("run.completed", {"conversationId": conversation.id})
        yield "event: message.completed\ndata: {}\n\n"
