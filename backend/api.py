import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agents.bridge_agent import BridgeAgent
from .agents.main_agent import MainAgent
from .agents.teacher_agent import TeacherAgent
from .agents.prompts import QA_TUTOR_SYSTEM
from .agents.registry import default_participants, get_agent, AGENTS
from .db import get_db
from .models import (
    BridgeNote,
    CardSection,
    Conversation,
    KnowledgeCard,
    LearningSpace,
    LearningRuntime,
    LearningRuntimeRecord,
    Message,
    Note,
    now,
    AIRun,
    RelatedCardProposal,
    TeacherGuidance,
)
from .schemas import (
    ConversationResponse,
    CreateKnowledgeCardRequest,
    CreateConversationRequest,
    CreateNoteRequest,
    LearningRuntimeResponse,
    UpdateLearningRuntimeRequest,
    KnowledgeCardResponse,
    NoteResponse,
    UpdateNoteRequest,
    AgentDefinitionResponse,
    RelatedCardProposalResponse,
    TeacherGuidanceResponse,
)
from .security.auth import require_current_user, current_user_id
from .services.provider_settings import restore_active_provider

router = APIRouter(dependencies=[Depends(require_current_user)])
public_router = APIRouter()

logger = logging.getLogger("studycenter.api")
"""Learning-domain routes."""

RELATION_LABELS = {
    "prerequisite": "前置知识",
    "deep_dive": "深入理解",
    "application": "应用延展",
}


def relation_label(relation_type: str | None) -> str:
    return RELATION_LABELS.get(relation_type or "prerequisite", "学习分支")

def owned_space(db: Session, space_id: str) -> LearningSpace:
    space = db.scalar(
        select(LearningSpace).where(
            LearningSpace.id == space_id,
            LearningSpace.user_id == current_user_id(),
        )
    )
    if not space:
        raise HTTPException(status_code=404, detail="Learning space not found")
    return space


def owned_card(db: Session, card_id: str) -> KnowledgeCard:
    card = db.scalar(
        select(KnowledgeCard)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(KnowledgeCard.id == card_id, LearningSpace.user_id == current_user_id())
    )
    if not card:
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return card


def owned_conversation(db: Session, conversation_id: str) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .join(KnowledgeCard, Conversation.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(Conversation.id == conversation_id, LearningSpace.user_id == current_user_id())
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@public_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@router.get("/agents", response_model=list[AgentDefinitionResponse])
def list_agents():
    return AGENTS


@router.get("/learning-spaces/{space_id}/runtime", response_model=LearningRuntimeResponse | None)
def get_learning_runtime(space_id: str, db: Session = Depends(get_db)):
    owned_space(db, space_id)
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    return db.scalar(select(LearningRuntime).where(LearningRuntime.space_id == space_id))


@router.put("/learning-spaces/{space_id}/runtime", response_model=LearningRuntimeResponse)
def update_learning_runtime(
    space_id: str,
    payload: UpdateLearningRuntimeRequest,
    db: Session = Depends(get_db),
):
    owned_space(db, space_id)
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    current_card = db.get(KnowledgeCard, payload.current_card_id)
    if not current_card or current_card.space_id != space_id or current_card.status == "deleted":
        raise HTTPException(status_code=400, detail="Current card does not belong to this learning space")
    if payload.current_section_id:
        current_section = db.get(CardSection, payload.current_section_id)
        if not current_section or current_section.card_id != current_card.id:
            raise HTTPException(status_code=400, detail="Current section does not belong to current card")

    stack = [entry.model_dump(by_alias=True) for entry in payload.navigation_stack]
    for entry in payload.navigation_stack:
        stack_card = db.get(KnowledgeCard, entry.card_id)
        if not stack_card or stack_card.space_id != space_id or stack_card.status == "deleted":
            raise HTTPException(status_code=400, detail="Navigation stack contains an invalid card")
        if entry.section_id:
            stack_section = db.get(CardSection, entry.section_id)
            if not stack_section or stack_section.card_id != stack_card.id:
                raise HTTPException(status_code=400, detail="Navigation stack contains an invalid section")

    runtime = db.scalar(select(LearningRuntime).where(LearningRuntime.space_id == space_id))
    if runtime is None:
        runtime = LearningRuntime(space_id=space_id)
        db.add(runtime)
        db.flush()
    source = payload.navigation_stack[-1] if payload.navigation_stack else None
    runtime.current_card_id = current_card.id
    runtime.current_section_id = payload.current_section_id
    runtime.source_card_id = source.card_id if source else None
    runtime.source_section_id = source.section_id if source else None
    runtime.navigation_stack_json = json.dumps(stack, ensure_ascii=False)
    runtime.updated_at = now()

    latest_seq = db.scalar(
        select(func.max(LearningRuntimeRecord.seq)).where(LearningRuntimeRecord.runtime_id == runtime.id)
    ) or 0
    db.add(LearningRuntimeRecord(
        runtime_id=runtime.id,
        seq=latest_seq + 1,
        event_type=payload.event_type,
        card_id=current_card.id,
        section_id=payload.current_section_id,
        payload_json=json.dumps({"navigationStack": stack}, ensure_ascii=False),
    ))
    db.commit()
    db.refresh(runtime)
    return runtime


@router.get("/learning-spaces/{space_id}/cards", response_model=list[KnowledgeCardResponse])
def list_cards(space_id: str, db: Session = Depends(get_db)):
    owned_space(db, space_id)
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    return list(
        db.scalars(
            select(KnowledgeCard)
            .where(KnowledgeCard.space_id == space_id, KnowledgeCard.status != "deleted")
            .order_by(KnowledgeCard.card_type, KnowledgeCard.title)
        )
    )


@router.post("/learning-spaces/{space_id}/cards", response_model=KnowledgeCardResponse, status_code=201)
def create_card(space_id: str, payload: CreateKnowledgeCardRequest, db: Session = Depends(get_db)):
    owned_space(db, space_id)
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    card = KnowledgeCard(space_id=space_id, **payload.model_dump())
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


@router.get("/cards/{card_id}", response_model=KnowledgeCardResponse)
def get_card(card_id: str, db: Session = Depends(get_db)):
    card = owned_card(db, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return card


@router.delete("/cards/{card_id}")
def delete_card(card_id: str, db: Session = Depends(get_db)):
    card = owned_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    if card.status != "deleted":
        card.status = "deleted"
        card.deleted_at = now()
        db.commit()
    return {"status": "deleted", "cardId": card_id}


@router.get("/cards/{card_id}/sections/{section_id}/guidance", response_model=list[TeacherGuidanceResponse])
def list_teacher_guidance(card_id: str, section_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    section = db.get(CardSection, section_id)
    if not section or section.card_id != card_id:
        raise HTTPException(status_code=404, detail="Card section not found")
    return list(
        db.scalars(
            select(TeacherGuidance)
            .where(TeacherGuidance.card_id == card_id, TeacherGuidance.section_id == section_id)
            .order_by(TeacherGuidance.created_at, TeacherGuidance.id)
        )
    )


@router.post("/cards/{card_id}/sections/{section_id}/guidance", response_model=TeacherGuidanceResponse, status_code=201)
async def create_section_guidance(card_id: str, section_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    section = db.get(CardSection, section_id)
    if not card or card.status == "deleted" or not section or section.card_id != card_id:
        raise HTTPException(status_code=404, detail="Card section not found")
    existing = db.scalar(
        select(TeacherGuidance)
        .where(
            TeacherGuidance.card_id == card_id,
            TeacherGuidance.section_id == section_id,
            TeacherGuidance.trigger == "section_enter",
        )
        .order_by(TeacherGuidance.created_at)
    )
    if existing:
        return existing
    draft = await TeacherAgent(restore_active_provider(db)).create_section_intro(
        card.title, section.title, section.content_markdown
    )
    guidance = TeacherGuidance(
        card_id=card_id,
        section_id=section_id,
        trigger="section_enter",
        content=draft.content,
    )
    db.add(guidance)
    db.commit()
    db.refresh(guidance)
    return guidance


@router.post("/cards/{card_id}/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(card_id: str, payload: CreateConversationRequest, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    section = db.get(CardSection, payload.section_id)
    if not section or section.card_id != card_id:
        raise HTTPException(status_code=400, detail="Section does not belong to this knowledge card")
    participant_ids = payload.participant_ids or default_participants(payload.conversation_type)
    unknown = [agent_id for agent_id in participant_ids if not get_agent(agent_id)]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {unknown[0]}")
    values = payload.model_dump(exclude={"participant_ids"})
    values["participant_ids_json"] = json.dumps(participant_ids)
    conversation = Conversation(card_id=card_id, **values)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/cards/{card_id}/conversations", response_model=list[ConversationResponse])
def list_conversations(
    card_id: str,
    section_id: str = Query(alias="sectionId"),
    db: Session = Depends(get_db),
):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    section = db.get(CardSection, section_id)
    if not section or section.card_id != card_id:
        raise HTTPException(status_code=400, detail="Section does not belong to this knowledge card")
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.card_id == card_id, Conversation.section_id == section_id)
            .order_by(Conversation.created_at, Conversation.id)
        )
    )


@router.get("/cards/{card_id}/proposals", response_model=list[RelatedCardProposalResponse])
def list_card_proposals(card_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return list(
        db.scalars(
            select(RelatedCardProposal)
            .where(
                RelatedCardProposal.card_id == card_id,
                RelatedCardProposal.status.in_(("pending", "discussing")),
            )
            .order_by(RelatedCardProposal.created_at.desc())
        )
    )



@router.post("/proposals/{proposal_id}/accept", response_model=KnowledgeCardResponse, status_code=201)
async def accept_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.get(RelatedCardProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    owned_card(db, proposal.card_id)
    if proposal.generated_card_id:
        card = db.get(KnowledgeCard, proposal.generated_card_id)
        if card:
            return card
    source_card = db.get(KnowledgeCard, proposal.card_id)
    if not source_card or source_card.status == "deleted":
        raise HTTPException(status_code=404, detail="Source card not found")
    draft = await MainAgent(restore_active_provider(db)).create_card(
        f"生成学习分支知识卡：{proposal.title}\n学习原因：{proposal.reason}"
    )
    card = KnowledgeCard(
        space_id=source_card.space_id,
        parent_card_id=source_card.id,
        parent_section_id=proposal.section_id,
        source_conversation_id=proposal.conversation_id,
        title=draft.title or proposal.title,
        card_type="related",
        relation_type=proposal.relation_type,
        status="active",
    )
    db.add(card)
    db.flush()
    for index, section in enumerate(draft.sections):
        db.add(CardSection(
            card_id=card.id,
            title=section.title or f"第 {index + 1} 节",
            order_index=index,
            content_markdown=section.content_markdown,
            content_type=section.content_type,
            teaching_objective=section.teaching_objective,
            quality_report_json=json.dumps(section.quality_report, ensure_ascii=False),
        ))
    bridge = await BridgeAgent(restore_active_provider(db)).create(source_card.title, card.title)
    db.add(BridgeNote(card_id=source_card.id, related_card_id=card.id, content=bridge.content))
    proposal.status = "accepted"
    proposal.generated_card_id = card.id
    db.commit()
    db.refresh(card)
    return card


@router.post("/proposals/{proposal_id}/discussion", response_model=ConversationResponse, status_code=201)
def start_proposal_discussion(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.get(RelatedCardProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    owned_card(db, proposal.card_id)
    if proposal.generated_card_id:
        raise HTTPException(status_code=400, detail="Proposal has already been accepted")
    section = db.get(CardSection, proposal.section_id) if proposal.section_id else None
    if not section or section.card_id != proposal.card_id:
        raise HTTPException(status_code=409, detail="Proposal is not associated with a valid course section")
    conversation = Conversation(
        card_id=proposal.card_id,
        section_id=proposal.section_id,
        conversation_type="side",
        title=f"讨论：{proposal.title}",
        root_question=(
            f"推荐学习主题：{proposal.title}\n"
            f"推荐原因：{proposal.reason}\n"
            f"请围绕这个{relation_label(proposal.relation_type)}建议帮助我判断是否值得创建一条学习分支。"
        ),
    )
    db.add(conversation)
    proposal.status = "discussing"
    db.commit()
    db.refresh(conversation)
    return conversation


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.get(RelatedCardProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    owned_card(db, proposal.card_id)
    proposal.status = "rejected"
    db.commit()
    return {"status": "rejected", "proposalId": proposal_id}


@router.post("/cards/{card_id}/notes", response_model=NoteResponse, status_code=201)
def create_note(card_id: str, payload: CreateNoteRequest, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    values = payload.model_dump()
    values["title"] = values.get("title") or values["content"].splitlines()[0][:200] or "未命名笔记"
    note = Note(card_id=card_id, **values)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("/cards/{card_id}/notes", response_model=list[NoteResponse])
def list_notes(card_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    return list(db.scalars(select(Note).where(Note.card_id == card_id).order_by(Note.updated_at.desc())))


@router.get("/notes", response_model=list[NoteResponse])
def list_all_notes(db: Session = Depends(get_db)):
    return list(db.scalars(
        select(Note)
        .join(KnowledgeCard, Note.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(LearningSpace.user_id == current_user_id())
        .order_by(Note.updated_at.desc())
    ))


@router.patch("/notes/{note_id}", response_model=NoteResponse)
def update_note(note_id: str, payload: UpdateNoteRequest, db: Session = Depends(get_db)):
    note = db.scalar(
        select(Note)
        .join(KnowledgeCard, Note.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(Note.id == note_id, LearningSpace.user_id == current_user_id())
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    values = payload.model_dump(exclude_unset=True)
    if "content" in values and not values["content"].strip():
        raise HTTPException(status_code=400, detail="Note content cannot be empty")
    for key, value in values.items():
        if value is not None:
            setattr(note, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(note)
    return note


@router.delete("/notes/{note_id}")
def delete_note(note_id: str, db: Session = Depends(get_db)):
    note = db.scalar(
        select(Note)
        .join(KnowledgeCard, Note.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(Note.id == note_id, LearningSpace.user_id == current_user_id())
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(note)
    db.commit()
    return {"status": "deleted", "noteId": note_id}
