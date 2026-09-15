from datetime import datetime
import json
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.utcnow()


class LearningSpace(Base):
    __tablename__ = "learning_spaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    learning_goal: Mapped[str] = mapped_column(Text)
    root_card_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    cards: Mapped[list["KnowledgeCard"]] = relationship(back_populates="space")


class KnowledgeCard(Base):
    __tablename__ = "knowledge_cards"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(ForeignKey("learning_spaces.id"))
    parent_card_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    card_type: Mapped[str] = mapped_column(String(20), default="root")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    space: Mapped[LearningSpace] = relationship(back_populates="cards")
    sections: Mapped[list["CardSection"]] = relationship(back_populates="card", cascade="all, delete-orphan")


class CardSection(Base):
    __tablename__ = "card_sections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    title: Mapped[str] = mapped_column(String(200))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    learning_status: Mapped[str] = mapped_column(String(20), default="unread")
    card: Mapped[KnowledgeCard] = relationship(back_populates="sections")


class TeacherGuidance(Base):
    __tablename__ = "teacher_guidance"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    section_id: Mapped[str] = mapped_column(ForeignKey("card_sections.id"))
    source_conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trigger: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    conversation_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    root_question: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20), default="single", server_default="single")
    participant_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    trigger_agent_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    director_policy: Mapped[str] = mapped_column(String(30), default="guided", server_default="guided")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    @property
    def participant_ids(self) -> list[str]:
        try:
            return json.loads(self.participant_ids_json)
        except (TypeError, json.JSONDecodeError):
            return []


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(20))
    sender_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sender_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="user", server_default="user")
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(30), default="text")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="未命名笔记")
    content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class RelatedCardProposal(Base):
    __tablename__ = "related_card_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    generated_card_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class BridgeNote(Base):
    __tablename__ = "bridge_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    related_card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ProviderCredential(Base):
    __tablename__ = "provider_credentials"
    provider_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    api_key_ciphertext: Mapped[str] = mapped_column(Text)
    api_key_nonce: Mapped[str] = mapped_column(String(50))
    encryption_key_version: Mapped[int] = mapped_column(Integer, default=1)
    models_json: Mapped[str] = mapped_column(Text, default="[]")
    active_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
