from datetime import datetime
import json
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.utcnow()


class LearningSpace(Base):
    __tablename__ = "learning_spaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200))
    learning_goal: Mapped[str] = mapped_column(Text)
    course_brief_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    course_scale: Mapped[str] = mapped_column(String(20), default="standard", server_default="standard")
    course_outline_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    root_card_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    generation_status: Mapped[str] = mapped_column(String(20), default="completed", server_default="completed")
    generation_phase: Mapped[str] = mapped_column(String(30), default="completed", server_default="completed")
    generation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=now, nullable=True)
    generation_lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    generation_lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    generation_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    cards: Mapped[list["KnowledgeCard"]] = relationship(back_populates="space")

    @property
    def course_brief(self) -> dict:
        try:
            value = json.loads(self.course_brief_json or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @course_brief.setter
    def course_brief(self, value: dict) -> None:
        self.course_brief_json = json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False)

    @property
    def course_outline(self) -> list[dict]:
        try:
            value = json.loads(self.course_outline_json or "[]")
            return value if isinstance(value, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    @course_outline.setter
    def course_outline(self, value: list[dict]) -> None:
        self.course_outline_json = json.dumps(value if isinstance(value, list) else [], ensure_ascii=False)


class CourseDesignSession(Base):
    """Server-owned state for the guided course design flow."""

    __tablename__ = "course_design_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_learning_space_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_spaces.id"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="collecting_goals")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    brief_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    brief_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    current_question_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    questions_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    recommended_scale: Mapped[str | None] = mapped_column(String(20), nullable=True)
    selected_scale: Mapped[str | None] = mapped_column(String(20), nullable=True)
    outline_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    outline_basis_brief_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outline_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processed_commands_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    operation_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    outline_revision_messages_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    __mapper_args__ = {"version_id_col": revision}

    @staticmethod
    def _load(value: str, fallback):
        try:
            parsed = json.loads(value or "")
            return parsed if isinstance(parsed, type(fallback)) else fallback
        except (TypeError, json.JSONDecodeError):
            return fallback

    @property
    def brief(self) -> dict:
        return self._load(self.brief_json, {})

    @brief.setter
    def brief(self, value: dict) -> None:
        self.brief_json = json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False)

    @property
    def current_question(self) -> dict:
        return self._load(self.current_question_json, {})

    @current_question.setter
    def current_question(self, value: dict) -> None:
        self.current_question_json = json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False)

    @property
    def questions(self) -> dict:
        return self._load(self.questions_json, {})

    @questions.setter
    def questions(self, value: dict) -> None:
        self.questions_json = json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False)

    @property
    def outline(self) -> list[dict]:
        return self._load(self.outline_json, [])

    @outline.setter
    def outline(self, value: list[dict]) -> None:
        self.outline_json = json.dumps(value if isinstance(value, list) else [], ensure_ascii=False)

    @property
    def processed_commands(self) -> list[str]:
        return self._load(self.processed_commands_json, [])

    @processed_commands.setter
    def processed_commands(self, value: list[str]) -> None:
        self.processed_commands_json = json.dumps(value if isinstance(value, list) else [], ensure_ascii=False)

    @property
    def operation(self) -> dict:
        return self._load(self.operation_json, {})

    @operation.setter
    def operation(self, value: dict) -> None:
        self.operation_json = json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False)

    @property
    def outline_revision_messages(self) -> list[dict]:
        return self._load(self.outline_revision_messages_json, [])

    @outline_revision_messages.setter
    def outline_revision_messages(self, value: list[dict]) -> None:
        self.outline_revision_messages_json = json.dumps(value if isinstance(value, list) else [], ensure_ascii=False)


class KnowledgeCard(Base):
    __tablename__ = "knowledge_cards"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(ForeignKey("learning_spaces.id"))
    parent_card_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    card_type: Mapped[str] = mapped_column(String(20), default="root")
    relation_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    course_plan_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    course_quality_report_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    generation_version: Mapped[str] = mapped_column(String(50), default="v2", server_default="v2")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    space: Mapped[LearningSpace] = relationship(back_populates="cards")
    sections: Mapped[list["CardSection"]] = relationship(back_populates="card", cascade="all, delete-orphan")

    @property
    def course_plan(self) -> dict:
        try:
            value = json.loads(self.course_plan_json or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @course_plan.setter
    def course_plan(self, value: dict) -> None:
        self.course_plan_json = json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False)

    @property
    def course_quality_report(self) -> dict:
        try:
            value = json.loads(self.course_quality_report_json or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}


class CardSection(Base):
    __tablename__ = "card_sections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    title: Mapped[str] = mapped_column(String(200))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    content_type: Mapped[str] = mapped_column(String(30), default="concept", server_default="concept")
    teaching_objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_report_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    plan_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    actual_summary_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    content_blocks_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    generation_status: Mapped[str] = mapped_column(String(30), default="completed", server_default="completed")
    generation_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    generation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_metadata_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    learning_status: Mapped[str] = mapped_column(String(20), default="unread")
    card: Mapped[KnowledgeCard] = relationship(back_populates="sections")

    @property
    def quality_report(self) -> dict:
        try:
            value = json.loads(self.quality_report_json)
            return value if isinstance(value, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @property
    def plan(self) -> dict:
        try:
            value = json.loads(self.plan_json or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @property
    def actual_summary(self) -> dict:
        try:
            value = json.loads(self.actual_summary_json or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}


class LearningRuntime(Base):
    __tablename__ = "learning_runtimes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(ForeignKey("learning_spaces.id"), unique=True)
    current_card_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_card_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    navigation_stack_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    @property
    def navigation_stack(self) -> list[dict[str, str | None]]:
        try:
            value = json.loads(self.navigation_stack_json)
            return value if isinstance(value, list) else []
        except (TypeError, json.JSONDecodeError):
            return []


class LearningRuntimeRecord(Base):
    __tablename__ = "learning_runtime_records"
    __table_args__ = (UniqueConstraint("runtime_id", "seq", name="uq_learning_runtime_record_seq"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    runtime_id: Mapped[str] = mapped_column(ForeignKey("learning_runtimes.id"))
    seq: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40), default="navigation")
    card_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LearningActivity(Base):
    __tablename__ = "learning_activities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    section_id: Mapped[str] = mapped_column(ForeignKey("card_sections.id"))
    activity_type: Mapped[str] = mapped_column(String(30), default="quiz")
    title: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ready")
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    answer_key_json: Mapped[str] = mapped_column(Text, default="{}")
    generation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class ActivityAttempt(Base):
    __tablename__ = "activity_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    activity_id: Mapped[str] = mapped_column(ForeignKey("learning_activities.id"))
    status: Mapped[str] = mapped_column(String(20), default="evaluated")
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mastery_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    diagnostic_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TeacherGuidance(Base):
    __tablename__ = "teacher_guidance"
    __table_args__ = (
        Index(
            "uq_teacher_guidance_section_enter",
            "card_id",
            "section_id",
            unique=True,
            sqlite_where=text("trigger = 'section_enter'"),
            postgresql_where=text("trigger = 'section_enter'"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    section_id: Mapped[str] = mapped_column(ForeignKey("card_sections.id"))
    source_conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_question_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_answer_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_question: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class AIRun(Base):
    __tablename__ = "ai_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    run_type: Mapped[str] = mapped_column(String(30), default="side_message")
    status: Mapped[str] = mapped_column(String(20), default="running")
    phase: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class AITaskUsage(Base):
    """A prompt-free audit row for one completed or failed gateway call."""
    __tablename__ = "ai_task_usage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    task: Mapped[str] = mapped_column(String(80), index=True)
    provider_name: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


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
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("learning_activities.id"), nullable=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("knowledge_cards.id"))
    section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    relation_type: Mapped[str] = mapped_column(String(30), default="prerequisite", server_default="prerequisite")
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
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    api_key_ciphertext: Mapped[str] = mapped_column(Text, default="")
    api_key_nonce: Mapped[str] = mapped_column(String(50), default="")
    auth_type: Mapped[str] = mapped_column(String(20), default="api_key", server_default="api_key")
    oauth_access_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_access_nonce: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oauth_refresh_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_refresh_nonce: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oauth_expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oauth_account_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    encryption_key_version: Mapped[int] = mapped_column(Integer, default=1)
    models_json: Mapped[str] = mapped_column(Text, default="[]")
    active_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    task_routes_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class TaskModelRoute(Base):
    __tablename__ = "task_model_routes"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    task: Mapped[str] = mapped_column(String(80), primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class DefaultModelPreference(Base):
    __tablename__ = "default_model_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    provider_name: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class InviteCode(Base):
    __tablename__ = "invite_codes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
