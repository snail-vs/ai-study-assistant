"""Quiz generation and activity attempt submission workflows."""

import json
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.assessment_agent import AssessmentAgent
from ..assessment import AttemptSubmissionService, LegacyQuizAdapter
from ..models import ActivityAttempt, CardSection, KnowledgeCard, LearningActivity, now
from .activity_hooks import run_post_assessment_hooks
from .activity_query import activity_attempt_response, activity_response
from .provider_settings import restore_active_provider

logger = logging.getLogger("studycenter.activity")


def _compatibility_module():
    import sys
    return sys.modules.get(__name__.rsplit(".", 1)[0] + "." + "activity_" + "workflow")


def _assessment_agent():
    return getattr(_compatibility_module(), "AssessmentAgent", AssessmentAgent)


def _restore_provider():
    return getattr(_compatibility_module(), "restore_active_provider", restore_active_provider)


def _post_assessment_hooks():
    return getattr(_compatibility_module(), "run_post_assessment_hooks", run_post_assessment_hooks)


async def generate_quiz(db: Session, card: KnowledgeCard, section: CardSection) -> dict:
    activity = db.scalar(select(LearningActivity).where(
        LearningActivity.section_id == section.id, LearningActivity.activity_type == "quiz",
    ))
    if activity and activity.status == "ready":
        attempt = db.scalar(select(ActivityAttempt).where(
            ActivityAttempt.activity_id == activity.id,
        ).order_by(ActivityAttempt.created_at.desc()))
        return activity_response(activity, attempt)
    if activity is None:
        activity = LearningActivity(
            card_id=card.id, section_id=section.id, activity_type="quiz", title="理解检查",
            objective=(
                section.teaching_objective
                or f"检查是否理解“{section.title}”的核心内容。"
            ),
            status="generating", content_json="{}", answer_key_json="{}",
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)
    else:
        activity.status = "generating"
        activity.generation_error = None
        db.commit()
    try:
        draft = await _assessment_agent()(_restore_provider()(db)).generate_quiz(
            card.title, section.title, activity.objective or "检查本节核心内容",
            section.content_markdown,
        )
        activity.title = draft.title
        activity.objective = draft.objective
        activity.content_json = json.dumps(
            {"version": 1, "questions": [item.model_dump(mode="json") for item in draft.questions]},
            ensure_ascii=False,
        )
        activity.answer_key_json = json.dumps(
            {
                item.question_id: item.model_dump(mode="json", by_alias=True)
                for item in draft.answer_key
            },
            ensure_ascii=False,
        )
        activity.status = "ready"
        db.commit()
        db.refresh(activity)
        return activity_response(activity)
    except Exception as exc:
        activity.status = "failed"
        activity.generation_error = str(exc)
        db.commit()
        raise


def _assessment_for_activity(activity: LearningActivity, section: CardSection | None) -> object:
    return LegacyQuizAdapter.from_json(
        activity_id=activity.id, objective=activity.objective,
        section_content=section.content_markdown if section else "",
        content=json.loads(activity.content_json or "{}"),
        answer_key=json.loads(activity.answer_key_json or "{}"),
    )


def _evaluator_factory(db: Session):
    def factory():
        return _assessment_agent()(_restore_provider()(db)).evaluate_short_answer
    return factory


async def submit_attempt(db: Session, activity: LearningActivity, answers: dict) -> dict:
    if activity.status != "ready":
        raise HTTPException(status_code=409, detail="Learning activity is not ready")
    section = db.get(CardSection, activity.section_id)
    card = db.get(KnowledgeCard, activity.card_id)
    assessment = _assessment_for_activity(activity, section)
    service = AttemptSubmissionService(short_answer_evaluator_factory=_evaluator_factory(db))
    submission = await service.submit(db, activity, assessment, answers)
    attempt = submission.attempt
    initial_result = json.loads(attempt.result_json or "{}")
    if attempt.status == "follow_up_pending":
        return activity_attempt_response(attempt)
    await _post_assessment_hooks()(
        db, activity, attempt, card, section,
        allow_gap_diagnosis=not initial_result.get("lowConfidence", False),
    )
    return activity_attempt_response(attempt)


async def submit_follow_up(
    db: Session, activity: LearningActivity, attempt: ActivityAttempt, answer: str
) -> dict:
    result = json.loads(attempt.result_json or "{}")
    follow_up = result.get("followUp")
    if not isinstance(follow_up, dict):
        raise HTTPException(status_code=409, detail="This attempt has no follow-up")
    if follow_up.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Follow-up has already been submitted")
    section = db.get(CardSection, activity.section_id)
    assessment = _assessment_for_activity(activity, section)
    evaluator_factory = _evaluator_factory(db)
    service = AttemptSubmissionService(short_answer_evaluator_factory=evaluator_factory)
    try:
        evaluation = await service.evaluate_follow_up(
            assessment, follow_up, answer, evaluator_factory()
        )
    except Exception:
        logger.exception(
            "activity follow-up evaluation failed: activity_id=%s attempt_id=%s",
            activity.id, attempt.id,
        )
        raise HTTPException(status_code=502, detail="Follow-up evaluation failed")
    score = int(getattr(evaluation, "score", 0))
    follow_up["status"] = "completed"
    follow_up["answer"] = answer
    follow_up["result"] = {
        "score": score,
        "correct": score >= 60,
        "feedback": getattr(evaluation, "feedback", ""),
    }
    original_mastery = attempt.mastery_level or "needs_review"
    follow_up_mastery = (
        "mastered" if original_mastery == "mastered" else "developing"
    ) if score >= 60 else original_mastery
    result["postFollowUpMastery"] = follow_up_mastery
    result["followUp"] = follow_up
    attempt.result_json = json.dumps(result, ensure_ascii=False)
    attempt.status = "evaluated"
    attempt.completed_at = now()
    db.commit()
    db.refresh(attempt)
    card = db.get(KnowledgeCard, activity.card_id)
    await _post_assessment_hooks()(db, activity, attempt, card, section)
    return activity_attempt_response(attempt)
