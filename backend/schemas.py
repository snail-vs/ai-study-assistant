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
    course_brief: "CourseBrief | None" = Field(default=None, alias="courseBrief")
    course_scale: Literal["quick", "standard", "series"] = Field(default="standard", alias="courseScale")
    course_outline: list["CourseOutlineItem"] = Field(
        default_factory=list, max_length=12, alias="courseOutline"
    )


class RetryLearningSpaceGenerationRequest(CreateLearningSpaceRequest):
    pass


class CourseBrief(ApiModel):
    """Structured learning requirements collected before generation."""

    topic: str = Field(default="", max_length=500)
    learning_outcome: str = Field(default="", alias="learningOutcome", max_length=2000)
    # Structured selections are additive to the legacy free-text fields.  The
    # latter remain available for old clients and for richer learner wording.
    learning_goals: list[str] = Field(default_factory=list, alias="learningGoals", max_length=20)
    learning_goal_details: str = Field(default="", alias="learningGoalDetails", max_length=2000)
    prior_knowledge: str = Field(default="", alias="priorKnowledge", max_length=2000)
    prior_knowledge_levels: list[str] = Field(default_factory=list, alias="priorKnowledgeLevels", max_length=20)
    prior_knowledge_details: str = Field(default="", alias="priorKnowledgeDetails", max_length=2000)
    use_case: str = Field(default="", alias="useCase", max_length=1000)
    focus: list[str] = Field(default_factory=list, max_length=20)
    excluded_topics: list[str] = Field(default_factory=list, alias="excludedTopics", max_length=20)
    preferred_style: list[str] = Field(default_factory=list, alias="preferredStyle", max_length=20)
    time_budget_minutes: int | None = Field(default=None, alias="timeBudgetMinutes", ge=5, le=100000)


class CourseOutlineItem(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2000)


class CourseIntakeMessage(ApiModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10000)


class CourseDesignTurnRequest(ApiModel):
    messages: list[CourseIntakeMessage] = Field(default_factory=list, max_length=20)
    brief: CourseBrief | None = None
    course_scale: Literal["quick", "standard", "series"] | None = Field(default=None, alias="courseScale")
    skip: bool = False


class CourseDesignTurnResponse(ApiModel):
    brief: CourseBrief
    assistant_message: str = Field(alias="assistantMessage")
    question: str | None = None
    quick_options: list[str] = Field(default_factory=list, alias="quickOptions", max_length=4)
    ready: bool
    recommended_scale: Literal["quick", "standard", "series"] = Field(alias="recommendedScale")
    course_scale: Literal["quick", "standard", "series"] = Field(alias="courseScale")
    outline: list[CourseOutlineItem] = Field(default_factory=list, max_length=12)
    turn: int = Field(ge=0, le=3)


class CourseOutlineRequest(ApiModel):
    brief: CourseBrief
    course_scale: Literal["quick", "standard", "series"] = Field(alias="courseScale")


class CourseOutlineResponse(ApiModel):
    course_scale: Literal["quick", "standard", "series"] = Field(alias="courseScale")
    outline: list[CourseOutlineItem] = Field(min_length=1, max_length=12)


class CourseOutlineRevisionMessage(ApiModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10000)


class CourseOutlineRevisionRequest(ApiModel):
    brief: CourseBrief
    course_scale: Literal["quick", "standard", "series"] = Field(alias="courseScale")
    current_outline: list[CourseOutlineItem] = Field(alias="currentOutline", min_length=1, max_length=12)
    feedback: str = Field(min_length=1, max_length=4000)
    messages: list[CourseOutlineRevisionMessage] = Field(default_factory=list, max_length=20)


class CourseOutlineRevisionResponse(ApiModel):
    course_scale: Literal["quick", "standard", "series"] = Field(alias="courseScale")
    outline: list[CourseOutlineItem] = Field(min_length=1, max_length=12)
    assistant_message: str = Field(alias="assistantMessage", min_length=1)


CourseDesignState = Literal[
    "collecting_goals",
    "collecting_background",
    "reviewing_brief",
    "reviewing_outline",
    "outline_confirmed",
    "course_queued",
    "cancelled",
]
CourseDesignCommandType = Literal[
    "answer_question",
    "complete_with_ai",
    "go_back",
    "update_brief",
    "select_scale",
    "generate_outline",
    "revise_outline",
    "confirm_outline",
    "generate_course",
    "restart",
]


class CourseDesignQuestionOption(ApiModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=300)


class CourseDesignQuestion(ApiModel):
    id: str = Field(min_length=1, max_length=100)
    stage: Literal["collecting_goals", "collecting_background"]
    target: Literal["learningGoals", "priorKnowledgeLevels"]
    type: Literal["multi_select_with_text"] = "multi_select_with_text"
    title: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=2000)
    options: list[CourseDesignQuestionOption] = Field(default_factory=list, max_length=12)
    allow_custom: bool = Field(default=True, alias="allowCustom")
    minimum_selections: int = Field(default=0, ge=0, le=12, alias="minimumSelections")


class CourseDesignAnswer(ApiModel):
    question_id: str = Field(alias="questionId", min_length=1)
    selected_option_ids: list[str] = Field(default_factory=list, alias="selectedOptionIds", max_length=12)
    custom_text: str = Field(default="", alias="customText", max_length=2000)


class CourseDesignAnswerPayload(ApiModel):
    model_config = ConfigDict(extra="forbid")
    answer: CourseDesignAnswer


class CourseDesignBriefUpdate(ApiModel):
    learning_outcome: str | None = Field(default=None, alias="learningOutcome", max_length=2000)
    prior_knowledge: str | None = Field(default=None, alias="priorKnowledge", max_length=2000)
    learning_goal_details: str | None = Field(default=None, alias="learningGoalDetails", max_length=2000)
    prior_knowledge_details: str | None = Field(default=None, alias="priorKnowledgeDetails", max_length=2000)
    use_case: str | None = Field(default=None, alias="useCase", max_length=1000)
    focus: list[str] | None = Field(default=None, max_length=20)
    excluded_topics: list[str] | None = Field(default=None, alias="excludedTopics", max_length=20)
    preferred_style: list[str] | None = Field(default=None, alias="preferredStyle", max_length=20)
    time_budget_minutes: int | None = Field(default=None, alias="timeBudgetMinutes", ge=5, le=100000)


class CourseDesignBriefPayload(ApiModel):
    model_config = ConfigDict(extra="forbid")
    brief: CourseDesignBriefUpdate


class CourseDesignScalePayload(ApiModel):
    model_config = ConfigDict(extra="forbid")
    course_scale: Literal["quick", "standard", "series"] = Field(alias="courseScale")


class CourseDesignRevisionPayload(ApiModel):
    model_config = ConfigDict(extra="forbid")
    feedback: str = Field(min_length=1, max_length=4000)


class CourseDesignEmptyPayload(ApiModel):
    model_config = ConfigDict(extra="forbid")


CourseDesignPayload = (
    CourseDesignAnswerPayload
    | CourseDesignBriefPayload
    | CourseDesignScalePayload
    | CourseDesignRevisionPayload
    | CourseDesignEmptyPayload
)


class CourseDesignCommandRequest(ApiModel):
    command_id: str = Field(alias="commandId", min_length=1, max_length=100)
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    type: CourseDesignCommandType
    payload: CourseDesignPayload = Field(default_factory=CourseDesignEmptyPayload)


class CourseDesignSessionCreateRequest(ApiModel):
    topic: str = Field(min_length=1, max_length=500)
    learning_space_id: str | None = Field(default=None, alias="learningSpaceId", min_length=1)


class CourseDesignSessionResponse(ApiModel):
    session_id: str = Field(alias="sessionId")
    learning_space_id: str | None = Field(default=None, alias="learningSpaceId")
    state: CourseDesignState
    revision: int = Field(ge=1)
    brief_revision: int = Field(alias="briefRevision", ge=0)
    brief: CourseBrief
    current_question: CourseDesignQuestion | None = Field(default=None, alias="currentQuestion")
    recommended_scale: Literal["quick", "standard", "series"] | None = Field(default=None, alias="recommendedScale")
    selected_scale: Literal["quick", "standard", "series"] | None = Field(default=None, alias="selectedScale")
    outline: list[CourseOutlineItem] = Field(default_factory=list, max_length=12)
    outline_confirmed: bool = Field(default=False, alias="outlineConfirmed")
    allowed_actions: list[CourseDesignCommandType] = Field(default_factory=list, alias="allowedActions")
    operation: dict = Field(default_factory=dict)
    outline_revision_messages: list[CourseOutlineRevisionMessage] = Field(
        default_factory=list, alias="outlineRevisionMessages", max_length=20
    )


class LearningSpaceResponse(ApiModel):
    id: str
    title: str
    learning_goal: str = Field(alias="learningGoal")
    root_card_id: str | None = Field(alias="rootCardId")
    generation_status: str = Field(alias="generationStatus")
    generation_phase: str = Field(alias="generationPhase")
    generation_error: str | None = Field(default=None, alias="generationError")
    course_brief: CourseBrief = Field(default_factory=CourseBrief, alias="courseBrief")
    course_scale: Literal["quick", "standard", "series"] = Field(default="standard", alias="courseScale")
    course_outline: list[CourseOutlineItem] = Field(default_factory=list, alias="courseOutline")
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


class SubmitActivityFollowUpRequest(ApiModel):
    answer: str = Field(min_length=1, max_length=4000)


class ActivityResultItem(ApiModel):
    question_id: str = Field(alias="questionId")
    correct: bool
    score: int
    feedback: str
    reference_answer: str | None = Field(default=None, alias="referenceAnswer")
    error_type: str | None = Field(default=None, alias="errorType")
    confidence: float | None = None
    missing_rubric_id: str | None = Field(default=None, alias="missingRubricId")


class ActivityFollowUpResponse(ApiModel):
    id: str
    parent_task_id: str = Field(alias="parentTaskId")
    prompt: str
    status: str
    result: dict | None = None


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
    follow_up: ActivityFollowUpResponse | None = Field(default=None, alias="followUp")
    post_follow_up_mastery: str | None = Field(default=None, alias="postFollowUpMastery")


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
    source_question_message_id: str | None = Field(default=None, alias="sourceQuestionMessageId")
    source_answer_message_id: str | None = Field(default=None, alias="sourceAnswerMessageId")
    source_question: str | None = Field(default=None, alias="sourceQuestion")
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
    relation_type: str | None = Field(default=None, alias="relationType")
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
    section_id: str = Field(alias="sectionId")


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
    section_id: str = Field(alias="sectionId")
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
    relation_type: str = Field(default="prerequisite", alias="relationType")
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
