import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agents.prompts import QA_TUTOR_SYSTEM
from .agents.registry import default_participants, get_agent, AGENTS
from .db import get_db
from .models import (
    CardSection,
    Conversation,
    KnowledgeCard,
    Message,
    now,
    AIRun,
)
from .schemas import (
    ConversationResponse,
    CreateConversationRequest,
    AgentDefinitionResponse,
)
from .security.auth import require_current_user, current_user_id
from .services.provider_settings import restore_active_provider
from .services.ownership import owned_card, owned_conversation, owned_space

router = APIRouter(dependencies=[Depends(require_current_user)])
public_router = APIRouter()

logger = logging.getLogger("studycenter.api")
"""Learning-domain routes."""

@public_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@router.get("/agents", response_model=list[AgentDefinitionResponse])
def list_agents():
    return AGENTS


@router.post("/cards/{card_id}/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(card_id: str, payload: CreateConversationRequest, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    section = db.get(CardSection, payload.section_id)
    if not section or section.card_id != card_id:
        raise HTTPException(status_code=400, detail="Section does not belong to this knowledge card")
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
        raise HTTPException(status_code=400, detail="Section does not belong to this knowledge card")
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.card_id == card_id, Conversation.section_id == section_id)
            .order_by(Conversation.created_at, Conversation.id)
        )
    )
