from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ErrorDetail(ApiModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)
    request_id: str = Field(alias="requestId")


class ErrorResponse(ApiModel):
    error: ErrorDetail


class ProviderSettingsResponse(ApiModel):
    active_provider: str = Field(alias="activeProvider")
    active_model: str | None = Field(alias="activeModel")
    providers: dict[str, bool]
    models: dict[str, list[str]]
    task_routes: dict[str, str] = Field(default_factory=dict, alias="taskRoutes")


class AgentDefinitionResponse(ApiModel):
    id: str
    name: str
    role: str
    description: str
    visible: bool
    priority: int


class ConfigureProviderRequest(ApiModel):
    api_key: str | None = Field(default=None, alias="apiKey", min_length=1)
    models: list[str] = Field(min_length=1)
    default_model: str | None = Field(default=None, alias="defaultModel", min_length=1)
    task_routes: dict[str, str] | None = Field(default=None, alias="taskRoutes")


class TaskRouteResponse(ApiModel):
    id: str
    label: str
    category: str
    model: str | None = None


class ConfigureTaskRoutesRequest(ApiModel):
    # Values use provider:model, e.g. deepseek:deepseek-chat.
    routes: dict[str, str] = Field(default_factory=dict)


class DiscoverModelsRequest(ApiModel):
    api_key: str | None = Field(default=None, alias="apiKey", min_length=1)


class DiscoverModelsResponse(ApiModel):
    models: list[str]


class SelectModelRequest(ApiModel):
    model: str = Field(min_length=1)


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


class CardSectionResponse(ApiModel):
    id: str
    title: str
    order_index: int = Field(alias="orderIndex")
    content_markdown: str = Field(alias="contentMarkdown")
    learning_status: str = Field(default="unread", alias="learningStatus")


class TeacherGuidanceResponse(ApiModel):
    id: str
    card_id: str = Field(alias="cardId")
    section_id: str = Field(alias="sectionId")
    source_conversation_id: str | None = Field(default=None, alias="sourceConversationId")
    trigger: str
    content: str
    created_at: datetime = Field(alias="createdAt")


class KnowledgeCardResponse(ApiModel):
    id: str
    space_id: str = Field(alias="spaceId")
    parent_card_id: str | None = Field(default=None, alias="parentCardId")
    parent_section_id: str | None = Field(default=None, alias="parentSectionId")
    source_conversation_id: str | None = Field(default=None, alias="sourceConversationId")
    title: str
    card_type: str = Field(alias="cardType")
    status: str
    deleted_at: datetime | None = Field(default=None, alias="deletedAt")
    sections: list[CardSectionResponse]


class CreateKnowledgeCardRequest(ApiModel):
    title: str
    card_type: Literal["root", "related"] = Field(default="root", alias="cardType")
    parent_card_id: str | None = Field(default=None, alias="parentCardId")
    parent_section_id: str | None = Field(default=None, alias="parentSectionId")
    source_conversation_id: str | None = Field(default=None, alias="sourceConversationId")


class CreateMessageRequest(ApiModel):
    content: str = Field(min_length=1)
    client_message_id: str | None = Field(default=None, alias="clientMessageId")


class MessageResponse(ApiModel):
    id: str
    conversation_id: str = Field(alias="conversationId")
    role: str
    sender_id: str | None = Field(default=None, alias="senderId")
    sender_name: str | None = Field(default=None, alias="senderName")
    sender_role: str | None = Field(default=None, alias="senderRole")
    visibility: str = "user"
    content: str
    message_type: str = Field(alias="messageType")
    created_at: datetime = Field(alias="createdAt")


class CreateConversationRequest(ApiModel):
    section_id: str | None = Field(default=None, alias="sectionId")
    conversation_type: Literal["main", "side"] = Field(alias="conversationType")
    title: str
    root_question: str = Field(alias="rootQuestion")
    mode: Literal["single", "group"] = "single"
    participant_ids: list[str] = Field(default_factory=list, alias="participantIds")
    trigger_agent_id: str | None = Field(default=None, alias="triggerAgentId")
    director_policy: Literal["guided", "deterministic", "llm"] = Field(default="guided", alias="directorPolicy")


class ConversationResponse(ApiModel):
    id: str
    card_id: str = Field(alias="cardId")
    section_id: str | None = Field(alias="sectionId")
    conversation_type: str = Field(alias="conversationType")
    title: str
    mode: str
    participant_ids: list[str] = Field(default_factory=list, alias="participantIds")
    trigger_agent_id: str | None = Field(default=None, alias="triggerAgentId")
    director_policy: str = Field(alias="directorPolicy")
    status: str
    created_at: datetime = Field(alias="createdAt")


class RelatedCardProposalResponse(ApiModel):
    id: str
    conversation_id: str = Field(alias="conversationId")
    card_id: str = Field(alias="cardId")
    section_id: str | None = Field(default=None, alias="sectionId")
    title: str
    reason: str
    status: str
    generated_card_id: str | None = Field(default=None, alias="generatedCardId")
    created_at: datetime = Field(alias="createdAt")


class CreateNoteRequest(ApiModel):
    section_id: str | None = Field(default=None, alias="sectionId")
    conversation_id: str | None = Field(default=None, alias="conversationId")
    source_message_id: str | None = Field(default=None, alias="sourceMessageId")
    title: str | None = Field(default=None, max_length=200)
    content: str = Field(min_length=1)
    source_type: Literal["manual", "saved_message"] = Field(default="manual", alias="sourceType")


class NoteResponse(ApiModel):
    id: str
    card_id: str = Field(alias="cardId")
    section_id: str | None = Field(alias="sectionId")
    conversation_id: str | None = Field(alias="conversationId")
    source_message_id: str | None = Field(alias="sourceMessageId")
    title: str
    content: str
    source_type: str = Field(alias="sourceType")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class UpdateNoteRequest(ApiModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, min_length=1)
