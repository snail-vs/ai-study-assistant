from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RegisterRequest(ApiModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=200)
    invite_code: str = Field(alias="inviteCode", min_length=1, max_length=200)


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class AuthUserResponse(ApiModel):
    id: str
    username: str


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


class ChatGptLoginRequest(ApiModel):
    method: Literal["device_code", "browser"] = "device_code"


class ChatGptLoginResponse(ApiModel):
    session_id: str = Field(alias="sessionId")
    method: Literal["device_code", "browser"]
    auth_url: str | None = Field(default=None, alias="authUrl")
    user_code: str | None = Field(default=None, alias="userCode")
    verification_uri: str | None = Field(default=None, alias="verificationUri")
    interval_seconds: int | None = Field(default=None, alias="intervalSeconds")


class ChatGptLoginStatusRequest(ApiModel):
    session_id: str = Field(alias="sessionId")


class ChatGptLoginCompleteRequest(ApiModel):
    session_id: str = Field(alias="sessionId")
    input: str = Field(min_length=1)


class ChatGptLoginStatusResponse(ApiModel):
    state: Literal["pending", "done", "failed", "unknown"]
    account_id: str | None = Field(default=None, alias="accountId")
    expires: int | None = None
    error: str | None = None


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
    generation_status: str = Field(alias="generationStatus")
    generation_phase: str = Field(alias="generationPhase")
    generation_error: str | None = Field(default=None, alias="generationError")
    created_at: datetime = Field(alias="createdAt")


class LearningSpaceList(ApiModel):
    items: list[LearningSpaceResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class GenerationStatusResponse(ApiModel):
    space_id: str = Field(alias="spaceId")
    status: str
    phase: str
    error: str | None = None
    root_card_id: str | None = Field(default=None, alias="rootCardId")
    updated_at: datetime = Field(alias="updatedAt")


class LearningNavigationEntry(ApiModel):
    card_id: str = Field(alias="cardId")
    section_id: str | None = Field(default=None, alias="sectionId")


class UpdateLearningRuntimeRequest(ApiModel):
    current_card_id: str = Field(alias="currentCardId")
    current_section_id: str | None = Field(default=None, alias="currentSectionId")
    navigation_stack: list[LearningNavigationEntry] = Field(default_factory=list, alias="navigationStack")
    event_type: str = Field(default="navigation", alias="eventType")


class LearningRuntimeResponse(ApiModel):
    id: str
    space_id: str = Field(alias="spaceId")
    current_card_id: str | None = Field(default=None, alias="currentCardId")
    current_section_id: str | None = Field(default=None, alias="currentSectionId")
    source_card_id: str | None = Field(default=None, alias="sourceCardId")
    source_section_id: str | None = Field(default=None, alias="sourceSectionId")
    navigation_stack: list[LearningNavigationEntry] = Field(default_factory=list, alias="navigationStack")
    updated_at: datetime = Field(alias="updatedAt")


class QuizOptionResponse(ApiModel):
    id: str
    text: str


class QuizQuestionResponse(ApiModel):
    id: str
    type: Literal["single_choice", "true_false", "short_answer"]
    prompt: str
    options: list[QuizOptionResponse] = Field(default_factory=list)


class LearningActivityResponse(ApiModel):
    id: str
    card_id: str = Field(alias="cardId")
    section_id: str = Field(alias="sectionId")
    activity_type: Literal["quiz", "practice", "lab"] = Field(alias="activityType")
    title: str
    objective: str | None = None
    status: str
    questions: list[QuizQuestionResponse] = Field(default_factory=list)
    latest_attempt: "ActivityAttemptResponse | None" = Field(default=None, alias="latestAttempt")
    created_at: datetime = Field(alias="createdAt")


class SubmitActivityAttemptRequest(ApiModel):
    answers: dict[str, str | bool | None] = Field(default_factory=dict)


class ActivityResultItem(ApiModel):
    question_id: str = Field(alias="questionId")
    correct: bool
    score: int
    feedback: str
    reference_answer: str | None = Field(default=None, alias="referenceAnswer")


class ActivityAttemptResponse(ApiModel):
    id: str
    activity_id: str = Field(alias="activityId")
    status: str
    score: int | None = None
    mastery_level: str | None = Field(default=None, alias="masteryLevel")
    diagnostic_summary: str | None = Field(default=None, alias="diagnosticSummary")
    results: list[ActivityResultItem] = Field(default_factory=list)
    created_at: datetime = Field(alias="createdAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")


class CardSectionResponse(ApiModel):
    id: str
    title: str
    order_index: int = Field(alias="orderIndex")
    content_markdown: str = Field(alias="contentMarkdown")
    content_type: str = Field(default="concept", alias="contentType")
    teaching_objective: str | None = Field(default=None, alias="teachingObjective")
    quality_report: dict[str, object] = Field(default_factory=dict, alias="qualityReport")
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
    section_id: str | None = Field(default=None, alias="sectionId")


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


class AIRunResponse(ApiModel):
    id: str
    conversation_id: str = Field(alias="conversationId")
    run_type: str = Field(alias="runType")
    status: str
    phase: str | None = None
    error_message: str | None = Field(default=None, alias="errorMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


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
    conversation_id: str | None = Field(default=None, alias="conversationId")
    activity_id: str | None = Field(default=None, alias="activityId")
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
