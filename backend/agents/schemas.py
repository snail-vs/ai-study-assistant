from typing import Literal

from pydantic import BaseModel, Field


class RelatedCardProposal(BaseModel):
    title: str
    reason: str


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


class KnowledgeCardDraft(BaseModel):
    title: str
    summary: str
    sections: list[CardSectionDraft]
