"""Learning-space routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import LearningSpace, now
from .schemas import (
    CreateLearningSpaceRequest,
    GenerationStatusResponse,
    LearningSpaceList,
    LearningSpaceResponse,
    RetryLearningSpaceGenerationRequest,
)
from .security.auth import current_user_id, require_current_user
from .services.course_generation import schedule_course_generation
from .services.ownership import owned_space

router = APIRouter(dependencies=[Depends(require_current_user)])


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
        generation_status="queued",
        generation_phase="queued",
    )
    db.add(space)
    db.commit()
    db.refresh(space)
    schedule_course_generation(space.id, user_id, payload.learning_goal)
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


@router.get("/learning-spaces/{space_id}/generation", response_model=GenerationStatusResponse)
def get_course_generation_status(space_id: str, db: Session = Depends(get_db)):
    space = owned_space(db, space_id)
    return {
        "spaceId": space.id,
        "status": space.generation_status,
        "phase": space.generation_phase,
        "error": space.generation_error,
        "rootCardId": space.root_card_id,
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
        raise HTTPException(status_code=409, detail="A completed course cannot be regenerated")
    space.title = payload.title
    space.learning_goal = payload.learning_goal
    space.generation_status = "queued"
    space.generation_phase = "queued"
    space.generation_error = None
    space.generation_updated_at = now()
    db.commit()
    db.refresh(space)
    schedule_course_generation(space.id, space.user_id, space.learning_goal)
    return space
