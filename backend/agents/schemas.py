from typing import Literal

from pydantic import BaseModel, Field


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
    content_type: Literal["concept", "practice", "summary", "quiz", "interactive"] = "concept"
    teaching_objective: str | None = None
    quality_report: dict[str, object] = Field(default_factory=dict)


class SectionPlanDraft(BaseModel):
    title: str
    teaching_objective: str
    content_type: Literal["concept", "practice", "summary", "quiz", "interactive"] = "concept"


class KnowledgeCardPlanDraft(BaseModel):
    title: str
    summary: str
    sections: list[SectionPlanDraft]


class SectionContentDraft(BaseModel):
    content_markdown: str


class SectionQualityReview(BaseModel):
    correctness: int = Field(ge=0, le=4)
    goal_alignment: int = Field(ge=0, le=4)
    clarity: int = Field(ge=0, le=4)
    information_density: int = Field(ge=0, le=4)
    blocking_issues: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)

    @property
    def needs_revision(self) -> bool:
        scores = (
            self.correctness,
            self.goal_alignment,
            self.clarity,
            self.information_density,
        )
        return bool(self.blocking_issues) or min(scores) < 3 or sum(scores) < 12


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


class CourseOutlineDraft(BaseModel):
    outline: list[CourseOutlineItemDraft] = Field(min_length=1)


class CourseOutlineRevisionDraft(BaseModel):
    outline: list[CourseOutlineItemDraft] = Field(min_length=1)
    assistant_message: str = Field(min_length=1)
