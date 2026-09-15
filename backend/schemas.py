from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CreateLearningSpaceRequest(ApiModel):
    title: str = Field(min_length=1)
    learning_goal: str = Field(alias="learningGoal", min_length=1)


class LearningSpaceResponse(ApiModel):
    id: str
    title: str
    learning_goal: str = Field(alias="learningGoal")
    root_card_id: str | None = Field(alias="rootCardId")
    created_at: datetime = Field(alias="createdAt")


class LearningSpaceList(ApiModel):
    items: list[LearningSpaceResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class CreateConversationRequest(ApiModel):
    section_id: str | None = Field(default=None, alias="sectionId")
    conversation_type: Literal["main", "side"] = Field(alias="conversationType")
    title: str
    root_question: str = Field(alias="rootQuestion")


class ConversationResponse(ApiModel):
    id: str
    card_id: str = Field(alias="cardId")
    section_id: str | None = Field(alias="sectionId")
    conversation_type: str = Field(alias="conversationType")
    title: str
    status: str
    created_at: datetime = Field(alias="createdAt")


class CreateNoteRequest(ApiModel):
    section_id: str | None = Field(default=None, alias="sectionId")
    conversation_id: str | None = Field(default=None, alias="conversationId")
    source_message_id: str | None = Field(default=None, alias="sourceMessageId")
    content: str = Field(min_length=1)
    source_type: Literal["manual", "saved_message"] = Field(default="manual", alias="sourceType")


class NoteResponse(ApiModel):
    id: str
    card_id: str = Field(alias="cardId")
    section_id: str | None = Field(alias="sectionId")
    conversation_id: str | None = Field(alias="conversationId")
    source_message_id: str | None = Field(alias="sourceMessageId")
    content: str
    source_type: str = Field(alias="sourceType")
    created_at: datetime = Field(alias="createdAt")
