from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SectionRole = Literal[
    "orientation",
    "concept",
    "mechanism",
    "comparison",
    "demonstration",
    "practice",
    "assessment",
    "transfer",
    "summary",
    "quiz",
    "interactive",
]


class RelatedCardProposal(BaseModel):
    title: str
    reason: str
    relation_type: Literal["prerequisite", "deep_dive", "application"] = "prerequisite"


class Diagnosis(BaseModel):
    has_knowledge_gap: bool = Field(alias="hasKnowledgeGap")
    missing_topics: list[str] = Field(default_factory=list, alias="missingTopics")


class SideAgentResult(BaseModel):
    reply: str
    diagnosis: Diagnosis
    proposal: RelatedCardProposal | None = None


class BridgeNoteDraft(BaseModel):
    content: str


class TeacherGuidanceDraft(BaseModel):
    content: str


class CardSectionDraft(BaseModel):
    title: str
    content_markdown: str
    content_type: SectionRole = "concept"
    teaching_objective: str | None = None
    quality_report: dict[str, object] = Field(default_factory=dict)
    plan: dict[str, object] = Field(default_factory=dict)
    actual_summary: dict[str, object] = Field(default_factory=dict)


class SectionPlanDraft(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    teaching_objective: str
    content_type: SectionRole = "concept"
    prerequisites: list[str] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)
    teaching_strategy: str = ""
    practice_task: str | None = None
    mastery_evidence: str = ""
    previous_connection: str = ""
    next_connection: str = ""
    estimated_minutes: int | None = Field(default=None, ge=1, le=10000)


class KnowledgeCardPlanDraft(BaseModel):
    title: str
    summary: str
    sections: list[SectionPlanDraft] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class SectionPlanDigest(BaseModel):
    title: str
    teaching_objective: str
    content_type: SectionRole
    key_concepts: list[str] = Field(default_factory=list)


class ActualSectionSummary(BaseModel):
    actually_taught: list[str] = Field(default_factory=list)
    assumed_knowledge: list[str] = Field(default_factory=list)
    examples_used: list[str] = Field(default_factory=list)
    misconceptions_addressed: list[str] = Field(default_factory=list)
    introduced_not_mastered: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_prerequisites: list[str] = Field(default_factory=list)
    summary: str = ""


class SectionGenerationContext(BaseModel):
    learner_brief: dict = Field(default_factory=dict)
    course_title: str
    course_summary: str
    course_plan: list[SectionPlanDigest]
    current_section: SectionPlanDraft
    previous_actual_summary: ActualSectionSummary | None = None
    taught_concepts: list[str] = Field(default_factory=list)
    introduced_not_mastered: list[str] = Field(default_factory=list)
    examples_already_used: list[str] = Field(default_factory=list)
    next_section: SectionPlanDigest | None = None


class SectionContentDraft(BaseModel):
    content_markdown: str


class SectionQualityReview(BaseModel):
    correctness: int = Field(ge=0, le=4)
    goal_alignment: int = Field(ge=0, le=4)
    clarity: int = Field(ge=0, le=4)
    information_density: int = Field(ge=0, le=4)
    prerequisite_fit: int = Field(default=4, ge=0, le=4)
    cognitive_load: int = Field(default=4, ge=0, le=4)
    example_quality: int = Field(default=4, ge=0, le=4)
    active_learning: int = Field(default=4, ge=0, le=4)
    personalization: int = Field(default=4, ge=0, le=4)
    blocking_issues: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)

    @property
    def needs_revision(self) -> bool:
        scores = (
            self.correctness,
            self.goal_alignment,
            self.clarity,
            self.information_density,
            self.prerequisite_fit,
            self.cognitive_load,
            self.example_quality,
            self.active_learning,
            self.personalization,
        )
        return bool(self.blocking_issues) or min(scores) < 3 or sum(scores) < 3 * len(scores)


class SectionQualityReport(BaseModel):
    initial_review: SectionQualityReview
    final_review: SectionQualityReview
    revision_attempted: bool = False
    quality_status: Literal["passed", "needs_attention"] = "passed"


class AnswerPlanDraft(BaseModel):
    intent: Literal[
        "definition",
        "mechanism",
        "comparison",
        "application",
        "debugging",
        "misconception",
        "other",
    ]
    direct_answer: str
    key_points: list[str] = Field(default_factory=list, max_length=4)
    needs_example: bool
    possible_knowledge_gap: bool
    target_length: Literal["short", "medium", "long"] = "short"


class QuizOption(BaseModel):
    id: str
    text: str


class QuizQuestion(BaseModel):
    id: str
    type: Literal["single_choice", "true_false", "short_answer"]
    prompt: str
    options: list[QuizOption] = Field(default_factory=list)


class QuizAnswerKey(BaseModel):
    question_id: str
    answer: str | bool | None = None
    explanation: str = ""
    reference_answer: str | None = None
    rubric: list[str] = Field(default_factory=list)


class QuizDraft(BaseModel):
    title: str = "理解检查"
    objective: str
    questions: list[QuizQuestion]
    answer_key: list[QuizAnswerKey]


class ShortAnswerEvaluation(BaseModel):
    score: int = Field(ge=0, le=100)
    feedback: str
    misconception: str | None = None
    # Optional fields keep compatibility with older providers.  Missing fields
    # deliberately mean "do not make a follow-up decision".
    error_type: str | None = Field(default=None, alias="errorType")
    confidence: float | None = Field(default=None, ge=0, le=1)
    missing_rubric: list[str] = Field(default_factory=list, alias="missingRubric")
    follow_up_question: str | None = Field(default=None, alias="followUpQuestion")


class KnowledgeCardDraft(BaseModel):
    title: str
    summary: str
    sections: list[CardSectionDraft]


class CourseIntakeResult(BaseModel):
    brief: dict = Field(default_factory=dict)
    assistant_message: str = Field(default="")
    question: str | None = None
    quick_options: list[str] = Field(default_factory=list)
    ready: bool = False
    recommended_scale: Literal["quick", "standard", "series"] = "standard"
    outline: list[dict] = Field(default_factory=list)


class CourseIntakeQuestionOption(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=300)


class CourseIntakeQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    stage: Literal["collecting_goals", "collecting_background"]
    target: Literal["learningGoals", "priorKnowledgeLevels"]
    type: Literal["multi_select_with_text"] = "multi_select_with_text"
    title: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=2000)
    options: list[CourseIntakeQuestionOption] = Field(default_factory=list, max_length=12)
    allow_custom: bool = Field(default=True, alias="allowCustom")
    minimum_selections: int = Field(default=0, ge=0, le=12, alias="minimumSelections")


class CourseIntakeDecision(BaseModel):
    type: Literal["ask_follow_up", "advance"]
    next_stage: Literal["collecting_goals", "collecting_background", "reviewing_brief"] = Field(alias="nextStage")
    reason: str = Field(default="", max_length=1000)


class CourseIntakeStateResult(BaseModel):
    brief_patch: dict = Field(default_factory=dict, alias="briefPatch")
    decision: CourseIntakeDecision
    assistant_message: str = Field(default="", alias="assistantMessage", max_length=2000)
    next_question: CourseIntakeQuestion | None = Field(default=None, alias="nextQuestion")
    recommended_scale: Literal["quick", "standard", "series"] | None = Field(default=None, alias="recommendedScale")


class CourseOutlineItemDraft(BaseModel):
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    role: SectionRole = "concept"
    prerequisites: list[str] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list, alias="keyConcepts")
    misconceptions: list[str] = Field(default_factory=list)
    teaching_strategy: str = Field(default="", alias="teachingStrategy")
    practice_task: str | None = Field(default=None, alias="practiceTask")
    mastery_evidence: str = Field(default="", alias="masteryEvidence")
    previous_connection: str = Field(default="", alias="previousConnection")
    next_connection: str = Field(default="", alias="nextConnection")
    estimated_minutes: int | None = Field(default=None, alias="estimatedMinutes", ge=1, le=10000)


class CourseOutlineDraft(BaseModel):
    outline: list[CourseOutlineItemDraft] = Field(min_length=1)


class CourseOutlineRevisionDraft(BaseModel):
    outline: list[CourseOutlineItemDraft] = Field(min_length=1)
    assistant_message: str = Field(min_length=1)
