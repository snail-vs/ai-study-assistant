"""Learning-space routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import (
    CardSection,
    CourseDesignSession,
    KnowledgeCard,
    LearningRuntime,
    LearningRuntimeRecord,
    LearningSpace,
    now,
)
from .schemas import (
    CreateLearningSpaceRequest,
    GenerationStatusResponse,
    LearningRuntimeResponse,
    LearningSpaceList,
    LearningSpaceResponse,
    RetryLearningSpaceGenerationRequest,
    UpdateLearningRuntimeRequest,
)
from .security.auth import current_user_id, require_current_user
from .services.course_generation import schedule_course_generation
from .services.ownership import owned_space

router = APIRouter(dependencies=[Depends(require_current_user)])


@router.get(
    "/learning-spaces/{space_id}/runtime",
    response_model=LearningRuntimeResponse | None,
)
def get_learning_runtime(space_id: str, db: Session = Depends(get_db)):
    owned_space(db, space_id)
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    return db.scalar(select(LearningRuntime).where(LearningRuntime.space_id == space_id))


@router.put(
    "/learning-spaces/{space_id}/runtime",
    response_model=LearningRuntimeResponse,
)
def update_learning_runtime(
    space_id: str,
    payload: UpdateLearningRuntimeRequest,
    db: Session = Depends(get_db),
):
    owned_space(db, space_id)
    if not db.get(LearningSpace, space_id):
        raise HTTPException(status_code=404, detail="Learning space not found")
    current_card = db.get(KnowledgeCard, payload.current_card_id)
    if (
        not current_card
        or current_card.space_id != space_id
        or current_card.status == "deleted"
    ):
        raise HTTPException(
            status_code=400,
            detail="Current card does not belong to this learning space",
        )
    if payload.current_section_id:
        current_section = db.get(CardSection, payload.current_section_id)
        if not current_section or current_section.card_id != current_card.id:
            raise HTTPException(
                status_code=400,
                detail="Current section does not belong to current card",
            )

    stack = [entry.model_dump(by_alias=True) for entry in payload.navigation_stack]
    for entry in payload.navigation_stack:
        stack_card = db.get(KnowledgeCard, entry.card_id)
        if (
            not stack_card
            or stack_card.space_id != space_id
            or stack_card.status == "deleted"
        ):
            raise HTTPException(
                status_code=400,
                detail="Navigation stack contains an invalid card",
            )
        if entry.section_id:
            stack_section = db.get(CardSection, entry.section_id)
            if not stack_section or stack_section.card_id != stack_card.id:
                raise HTTPException(
                    status_code=400,
                    detail="Navigation stack contains an invalid section",
                )

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
        select(func.max(LearningRuntimeRecord.seq)).where(
            LearningRuntimeRecord.runtime_id == runtime.id
        )
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


@router.post(
    "/learning-spaces",
    response_model=LearningSpaceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_learning_space(
    payload: CreateLearningSpaceRequest,
    db: Session = Depends(get_db),
):
    user_id = current_user_id()
    space = LearningSpace(
        user_id=user_id,
        title=payload.title,
        learning_goal=payload.learning_goal,
        course_brief_json=json.dumps(
            (payload.course_brief or {}).model_dump(by_alias=True) if payload.course_brief else {},
            ensure_ascii=False,
        ),
        course_scale=payload.course_scale,
        course_outline_json=json.dumps(
            [item.model_dump(by_alias=True) for item in payload.course_outline], ensure_ascii=False
        ),
        generation_status="queued",
        generation_phase="queued",
    )
    db.add(space)
    db.commit()
    db.refresh(space)
    schedule_course_generation(space.id, user_id, payload.learning_goal, payload.course_brief, payload.course_scale, payload.course_outline)
    return space


@router.get("/learning-spaces", response_model=LearningSpaceList)
def list_learning_spaces(db: Session = Depends(get_db)):
    return {
        "items": list(
            db.scalars(
                select(LearningSpace)
                .where(LearningSpace.user_id == current_user_id())
                .order_by(LearningSpace.created_at.desc())
            )
        )
    }


@router.get("/learning-spaces/{space_id}", response_model=LearningSpaceResponse)
def get_learning_space(space_id: str, db: Session = Depends(get_db)):
    return owned_space(db, space_id)


@router.delete("/learning-spaces/{space_id}")
def delete_failed_learning_space(space_id: str, db: Session = Depends(get_db)):
    space = owned_space(db, space_id)
    if space.generation_status != "failed":
        raise HTTPException(
            status_code=409,
            detail="Only failed course generations can be deleted",
        )
    cards = list(db.scalars(select(KnowledgeCard).where(KnowledgeCard.space_id == space_id)))
    if any(card.status != "draft" for card in cards):
        raise HTTPException(
            status_code=409,
            detail="A learning space with published knowledge cards cannot be deleted here",
        )
    existing_runtime = db.scalar(
        select(LearningRuntime).where(LearningRuntime.space_id == space_id)
    )
    if existing_runtime:
        raise HTTPException(
            status_code=409,
            detail="A learning space with learning progress cannot be deleted here",
        )

    sessions = list(
        db.scalars(
            select(CourseDesignSession).where(
                CourseDesignSession.source_learning_space_id == space_id
            )
        )
    )
    for session in sessions:
        db.delete(session)
    for card in cards:
        db.delete(card)
    db.delete(space)
    db.commit()
    return {"status": "deleted", "spaceId": space_id}


@router.get("/learning-spaces/{space_id}/generation", response_model=GenerationStatusResponse)
def get_course_generation_status(space_id: str, db: Session = Depends(get_db)):
    space = owned_space(db, space_id)
    sections = []
    if space.root_card_id:
        sections = list(db.scalars(
            select(CardSection)
            .where(CardSection.card_id == space.root_card_id)
            .order_by(CardSection.order_index)
        ))
    completed = sum(
        section.generation_status in {"completed", "needs_attention"}
        for section in sections
    )
    current = next(
        (section for section in sections if section.generation_status in {"generating", "reviewing"}),
        None,
    )
    return {
        "spaceId": space.id,
        "status": space.generation_status,
        "phase": space.generation_phase,
        "error": space.generation_error,
        "rootCardId": space.root_card_id,
        "completedSections": completed,
        "totalSections": len(sections),
        "currentSectionTitle": current.title if current else None,
        "updatedAt": space.generation_updated_at or space.created_at,
    }


@router.put("/learning-spaces/{space_id}/generation", response_model=LearningSpaceResponse)
async def retry_course_generation(
    space_id: str,
    payload: RetryLearningSpaceGenerationRequest,
    db: Session = Depends(get_db),
):
    space = owned_space(db, space_id)
    if space.generation_status != "failed":
        raise HTTPException(status_code=409, detail="Only failed course generations can be retried")
    if space.root_card_id:
        root_card = db.get(KnowledgeCard, space.root_card_id)
        if root_card and root_card.status == "active":
            raise HTTPException(status_code=409, detail="A completed course cannot be regenerated")
    space.title = payload.title
    space.learning_goal = payload.learning_goal
    if payload.course_brief is not None:
        space.course_brief = payload.course_brief.model_dump(by_alias=True)
    space.course_scale = payload.course_scale
    space.course_outline = [item.model_dump(by_alias=True) for item in payload.course_outline]
    space.generation_status = "queued"
    space.generation_phase = "queued"
    space.generation_error = None
    space.generation_updated_at = now()
    db.commit()
    db.refresh(space)
    schedule_course_generation(space.id, space.user_id, space.learning_goal, payload.course_brief, payload.course_scale, payload.course_outline)
    return space
