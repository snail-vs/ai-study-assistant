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


class KnowledgeCardDraft(BaseModel):
    title: str
    summary: str
    sections: list[CardSectionDraft]
