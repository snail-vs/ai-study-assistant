from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    conversation_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    root_question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
