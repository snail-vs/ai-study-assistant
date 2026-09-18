"""User-scoped lookups shared by the backend routers."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Conversation, KnowledgeCard, LearningSpace
from ..security.auth import current_user_id


def owned_space(db: Session, space_id: str) -> LearningSpace:
    space = db.scalar(
        select(LearningSpace).where(
            LearningSpace.id == space_id,
            LearningSpace.user_id == current_user_id(),
        )
    )
    if not space:
        raise HTTPException(status_code=404, detail="Learning space not found")
    return space


def owned_card(db: Session, card_id: str) -> KnowledgeCard:
    card = db.scalar(
        select(KnowledgeCard)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(KnowledgeCard.id == card_id, LearningSpace.user_id == current_user_id())
    )
    if not card:
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return card


def owned_conversation(db: Session, conversation_id: str) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .join(KnowledgeCard, Conversation.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(Conversation.id == conversation_id, LearningSpace.user_id == current_user_id())
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation
