"""Knowledge-card, guidance, proposal, and note routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .agents.teacher_agent import TeacherAgent
from .db import get_db
from .models import (
    CardSection,
    KnowledgeCard,
    LearningSpace,
    Note,
    RelatedCardProposal,
    TeacherGuidance,
    now,
)
from .schemas import (
    CreateKnowledgeCardRequest,
    CreateNoteRequest,
    KnowledgeCardResponse,
    NoteResponse,
    RelatedCardProposalResponse,
    TeacherGuidanceResponse,
    UpdateNoteRequest,
    ConversationResponse,
)
from .security.auth import current_user_id, require_current_user
from .services.ownership import owned_card, owned_space
from .services.related_card_workflow import (
    accept_proposal as accept_proposal_workflow,
    reject_proposal as reject_proposal_workflow,
    start_proposal_discussion as start_proposal_discussion_workflow,
)
from .services.provider_settings import restore_active_provider

router = APIRouter(dependencies=[Depends(require_current_user)])

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


@router.post(
    "/learning-spaces/{space_id}/cards",
    response_model=KnowledgeCardResponse,
    status_code=201,
)
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


@router.get(
    "/cards/{card_id}/sections/{section_id}/guidance",
    response_model=list[TeacherGuidanceResponse],
)
def list_teacher_guidance(card_id: str, section_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    section = db.get(CardSection, section_id)
    if not section or section.card_id != card_id:
        raise HTTPException(status_code=404, detail="Card section not found")
    return list(
        db.scalars(
            select(TeacherGuidance)
            .where(
                TeacherGuidance.card_id == card_id,
                TeacherGuidance.section_id == section_id,
                TeacherGuidance.content != "",
            )
            .order_by(TeacherGuidance.created_at, TeacherGuidance.id)
        )
    )


@router.post(
    "/cards/{card_id}/sections/{section_id}/guidance",
    response_model=TeacherGuidanceResponse,
    status_code=201,
)
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
    if (
        section.generation_status not in {"completed", "needs_attention"}
        or not section.content_markdown.strip()
    ):
        raise HTTPException(status_code=409, detail="Section content is still being generated")

    # Persist an empty row before the provider call. The partial unique index makes
    # this an inter-process generation claim, not just a read-before-write check.
    guidance = TeacherGuidance(
        card_id=card_id,
        section_id=section_id,
        trigger="section_enter",
        content="",
    )
    db.add(guidance)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        claimed = db.scalar(
            select(TeacherGuidance).where(
                TeacherGuidance.card_id == card_id,
                TeacherGuidance.section_id == section_id,
                TeacherGuidance.trigger == "section_enter",
            )
            .order_by(TeacherGuidance.created_at, TeacherGuidance.id)
        )
        if claimed:
            return claimed
        raise

    db.refresh(guidance)
    try:
        draft = await TeacherAgent(restore_active_provider(db)).create_section_intro(
            card.title, section.title, section.content_markdown
        )
        guidance.content = draft.content
        db.commit()
        db.refresh(guidance)
    except Exception:
        db.delete(guidance)
        db.commit()
        raise
    return guidance


@router.get(
    "/cards/{card_id}/proposals",
    response_model=list[RelatedCardProposalResponse],
)
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


@router.post(
    "/proposals/{proposal_id}/accept",
    response_model=KnowledgeCardResponse,
    status_code=201,
)
async def accept_proposal(proposal_id: str, db: Session = Depends(get_db)):
    return await accept_proposal_workflow(proposal_id, db)


@router.post(
    "/proposals/{proposal_id}/discussion",
    response_model=ConversationResponse,
    status_code=201,
)
def start_proposal_discussion(proposal_id: str, db: Session = Depends(get_db)):
    return start_proposal_discussion_workflow(proposal_id, db)


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, db: Session = Depends(get_db)):
    return reject_proposal_workflow(proposal_id, db)


@router.post(
    "/cards/{card_id}/notes",
    response_model=NoteResponse,
    status_code=201,
)
def create_note(card_id: str, payload: CreateNoteRequest, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    card = db.get(KnowledgeCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Knowledge card not found")
    values = payload.model_dump()
    values["title"] = (
        values.get("title") or values["content"].splitlines()[0][:200] or "未命名笔记"
    )
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
    return list(
        db.scalars(select(Note).where(Note.card_id == card_id).order_by(Note.updated_at.desc()))
    )


@router.get("/notes", response_model=list[NoteResponse])
def list_all_notes(db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Note)
            .join(KnowledgeCard, Note.card_id == KnowledgeCard.id)
            .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
            .where(LearningSpace.user_id == current_user_id())
            .order_by(Note.updated_at.desc())
        )
    )


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
