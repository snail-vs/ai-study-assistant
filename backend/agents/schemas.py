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


class KnowledgeCardDraft(BaseModel):
    title: str
    summary: str
    sections: list[CardSectionDraft]
