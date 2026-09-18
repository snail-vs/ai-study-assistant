"""Learning activity HTTP routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import owned_card
from .db import get_db
from .models import ActivityAttempt, CardSection, KnowledgeCard, LearningActivity
from .schemas import (
    ActivityAttemptResponse,
    LearningActivityResponse,
    SubmitActivityAttemptRequest,
    SubmitActivityFollowUpRequest,
)
from .security.auth import require_current_user
from .services.activity_workflow import (
    activity_attempt_response,
    activity_response,
    generate_quiz,
    get_activity,
    submit_attempt,
    submit_follow_up,
)

router = APIRouter(dependencies=[Depends(require_current_user)])


@router.get(
    "/cards/{card_id}/sections/{section_id}/activities",
    response_model=list[LearningActivityResponse],
)
def list_section_activities(card_id: str, section_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    section = db.get(CardSection, section_id)
    card = db.get(KnowledgeCard, card_id)
    if not section or not card or section.card_id != card_id or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Section not found")
    activities = list(db.scalars(select(LearningActivity).where(
        LearningActivity.card_id == card_id,
        LearningActivity.section_id == section_id,
    ).order_by(LearningActivity.created_at)))
    return [activity_response(activity, db.scalar(select(ActivityAttempt).where(
        ActivityAttempt.activity_id == activity.id,
    ).order_by(ActivityAttempt.created_at.desc()))) for activity in activities]


@router.post(
    "/cards/{card_id}/sections/{section_id}/activities/quiz",
    response_model=LearningActivityResponse,
)
async def generate_section_quiz(card_id: str, section_id: str, db: Session = Depends(get_db)):
    owned_card(db, card_id)
    section = db.get(CardSection, section_id)
    card = db.get(KnowledgeCard, card_id)
    if not section or not card or section.card_id != card_id or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Section not found")
    return await generate_quiz(db, card, section)


@router.get("/activities/{activity_id}", response_model=LearningActivityResponse)
def get_learning_activity(activity_id: str, db: Session = Depends(get_db)):
    activity = get_activity(activity_id, db)
    attempt = db.scalar(select(ActivityAttempt).where(
        ActivityAttempt.activity_id == activity.id,
    ).order_by(ActivityAttempt.created_at.desc()))
    return activity_response(activity, attempt)


@router.get(
    "/activities/{activity_id}/attempts/latest",
    response_model=ActivityAttemptResponse | None,
)
def get_latest_activity_attempt(activity_id: str, db: Session = Depends(get_db)):
    activity = get_activity(activity_id, db)
    attempt = db.scalar(select(ActivityAttempt).where(
        ActivityAttempt.activity_id == activity.id,
    ).order_by(ActivityAttempt.created_at.desc()))
    return activity_attempt_response(attempt)


@router.post("/activities/{activity_id}/attempts", response_model=ActivityAttemptResponse)
async def submit_activity_attempt(
    activity_id: str,
    payload: SubmitActivityAttemptRequest,
    db: Session = Depends(get_db),
):
    activity = get_activity(activity_id, db)
    return await submit_attempt(db, activity, payload.answers)


@router.post(
    "/activities/{activity_id}/attempts/{attempt_id}/follow-up",
    response_model=ActivityAttemptResponse,
)
async def submit_activity_follow_up(
    activity_id: str,
    attempt_id: str,
    payload: SubmitActivityFollowUpRequest,
    db: Session = Depends(get_db),
):
    activity = get_activity(activity_id, db)
    attempt = db.get(ActivityAttempt, attempt_id)
    if not attempt or attempt.activity_id != activity.id:
        raise HTTPException(status_code=404, detail="Activity attempt not found")
    return await submit_follow_up(db, activity, attempt, payload.answer)
