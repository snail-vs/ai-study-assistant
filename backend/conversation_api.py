import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agents.registry import default_participants, get_agent
from .db import get_db
from .models import AIRun, CardSection, Conversation, KnowledgeCard, Message, now
from .schemas import (
    AIRunResponse,
    ConversationResponse,
    CreateConversationRequest,
    CreateMessageRequest,
    MessageResponse,
)
from .security.auth import require_current_user
from .services.conversation_stream import ConversationStreamService
from .services.ownership import owned_card, owned_conversation

router = APIRouter(dependencies=[Depends(require_current_user)])


@router.post(
    "/cards/{card_id}/conversations", response_model=ConversationResponse, status_code=201
)
def create_conversation(
    card_id: str, payload: CreateConversationRequest, db: Session = Depends(get_db)
):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    section = db.get(CardSection, payload.section_id)
    if not section or section.card_id != card_id:
        raise HTTPException(
            status_code=400, detail="Section does not belong to this knowledge card"
        )
    participant_ids = payload.participant_ids or default_participants(payload.conversation_type)
    unknown = [agent_id for agent_id in participant_ids if not get_agent(agent_id)]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {unknown[0]}")
    values = payload.model_dump(exclude={"participant_ids"})
    values["participant_ids_json"] = json.dumps(participant_ids)
    conversation = Conversation(card_id=card_id, **values)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/cards/{card_id}/conversations", response_model=list[ConversationResponse])
def list_conversations(
    card_id: str,
    section_id: str = Query(alias="sectionId"),
    db: Session = Depends(get_db),
):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    section = db.get(CardSection, section_id)
    if not section or section.card_id != card_id:
        raise HTTPException(
            status_code=400, detail="Section does not belong to this knowledge card"
        )
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.card_id == card_id, Conversation.section_id == section_id)
            .order_by(Conversation.created_at, Conversation.id)
        )
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(conversation_id: str, db: Session = Depends(get_db)):
    owned_conversation(db, conversation_id)
    conversation = db.get(Conversation, conversation_id)
    card = db.get(KnowledgeCard, conversation.card_id) if conversation else None
    if not conversation or not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Conversation not found")
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
    )


@router.get("/conversations/{conversation_id}/runs/active", response_model=AIRunResponse | None)
def get_active_run(conversation_id: str, db: Session = Depends(get_db)):
    owned_conversation(db, conversation_id)
    run = db.scalar(
        select(AIRun)
        .where(AIRun.conversation_id == conversation_id, AIRun.status.in_(("queued", "running")))
        .order_by(AIRun.created_at.desc())
    )
    if run and run.updated_at and (now() - run.updated_at).total_seconds() > 180:
        run.status = "expired"
        run.phase = "expired"
        run.error_message = "AI 请求可能已中断，请重新发送。"
        db.commit()
    return run


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: str,
    payload: CreateMessageRequest,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    owned_conversation(db, conversation_id)
    conversation = db.get(Conversation, conversation_id)
    card = db.get(KnowledgeCard, conversation.card_id) if conversation else None
    if not conversation or not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not conversation.section_id:
        raise HTTPException(
            status_code=409,
            detail="Legacy course-level conversations cannot receive section messages",
        )
    if payload.section_id != conversation.section_id:
        raise HTTPException(status_code=409, detail="Conversation belongs to a different section")
    active_run = db.scalar(
        select(AIRun)
        .where(AIRun.conversation_id == conversation_id, AIRun.status.in_(("queued", "running")))
        .order_by(AIRun.created_at.desc())
    )
    if active_run:
        raise HTTPException(
            status_code=409,
            detail="该问题讨论正在处理上一条消息，请稍候",
        )

    service = ConversationStreamService(db)
    context = service.prepare(conversation, card, payload)
    return StreamingResponse(service.events(context), media_type="text/event-stream")
