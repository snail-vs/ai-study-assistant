"""Learning activity projections and assessment workflow orchestration."""

import json
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.assessment_agent import AssessmentAgent
from ..agents.side_agent import SideAgent
from ..agents.teacher_agent import TeacherAgent
from ..assessment import AttemptSubmissionService, LegacyQuizAdapter
from ..models import (
    ActivityAttempt,
    CardSection,
    KnowledgeCard,
    LearningActivity,
    LearningSpace,
    RelatedCardProposal,
    TeacherGuidance,
    now,
)
from ..security.auth import current_user_id
from .provider_settings import restore_active_provider

logger = logging.getLogger("studycenter.activity")


def activity_attempt_response(attempt: ActivityAttempt | None) -> dict | None:
    if not attempt:
        return None
    result = json.loads(attempt.result_json or "{}")
    follow_up = result.get("followUp")
    public_follow_up = None
    if isinstance(follow_up, dict) and follow_up.get("id") and follow_up.get("parentTaskId"):
        public_follow_up = {
            "id": follow_up["id"],
            "parentTaskId": follow_up["parentTaskId"],
            "prompt": follow_up.get("prompt", ""),
            "status": follow_up.get("status", "pending"),
        }
        if isinstance(follow_up.get("result"), dict):
            public_follow_up["result"] = follow_up["result"]
    results = []
    for item in result.get("items", []):
        if not isinstance(item, dict):
            continue
        # Explicit whitelist: never project private rubric indexes, answer keys,
        # or provider payloads from result_json.
        results.append({key: item[key] for key in (
            "questionId", "correct", "score", "feedback", "referenceAnswer",
            "errorType", "confidence", "missingRubricId",
        ) if key in item})
    return {
        "id": attempt.id,
        "activityId": attempt.activity_id,
        "status": attempt.status,
        "score": attempt.score,
        "masteryLevel": attempt.mastery_level,
        "diagnosticSummary": attempt.diagnostic_summary,
        "results": results,
        "createdAt": attempt.created_at,
        "completedAt": attempt.completed_at,
        "followUp": public_follow_up,
        "postFollowUpMastery": result.get("postFollowUpMastery"),
    }


def activity_response(
    activity: LearningActivity,
    attempt: ActivityAttempt | None = None,
) -> dict:
    content = json.loads(activity.content_json or "{}")
    return {
        "id": activity.id,
        "cardId": activity.card_id,
        "sectionId": activity.section_id,
        "activityType": activity.activity_type,
        "title": activity.title,
        "objective": activity.objective,
        "status": activity.status,
        "questions": content.get("questions", []),
        "latestAttempt": activity_attempt_response(attempt),
        "createdAt": activity.created_at,
    }


def get_activity(activity_id: str, db: Session) -> LearningActivity:
    activity = db.scalar(
        select(LearningActivity)
        .join(KnowledgeCard, LearningActivity.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(LearningActivity.id == activity_id, LearningSpace.user_id == current_user_id())
    )
    section = db.get(CardSection, activity.section_id) if activity else None
    card = db.get(KnowledgeCard, activity.card_id) if activity else None
    if not activity or not section or not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Learning activity not found")
    return activity


async def generate_quiz(db: Session, card: KnowledgeCard, section: CardSection) -> dict:
    activity = db.scalar(select(LearningActivity).where(
        LearningActivity.section_id == section.id,
        LearningActivity.activity_type == "quiz",
    ))
    if activity and activity.status == "ready":
        attempt = db.scalar(select(ActivityAttempt).where(
            ActivityAttempt.activity_id == activity.id,
        ).order_by(ActivityAttempt.created_at.desc()))
        return activity_response(activity, attempt)
    if activity is None:
        activity = LearningActivity(
            card_id=card.id,
            section_id=section.id,
            activity_type="quiz",
            title="理解检查",
            objective=(
                section.teaching_objective
                or f"检查是否理解“{section.title}”的核心内容。"
            ),
            status="generating",
            content_json="{}",
            answer_key_json="{}",
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)
    else:
        activity.status = "generating"
        activity.generation_error = None
        db.commit()
    try:
        draft = await AssessmentAgent(restore_active_provider(db)).generate_quiz(
            card.title,
            section.title,
            activity.objective or "检查本节核心内容",
            section.content_markdown,
        )
        activity.title = draft.title
        activity.objective = draft.objective
        activity.content_json = json.dumps(
            {"version": 1, "questions": [
                item.model_dump(mode="json") for item in draft.questions
            ]},
            ensure_ascii=False,
        )
        activity.answer_key_json = json.dumps(
            {item.question_id: item.model_dump(mode="json", by_alias=True)
             for item in draft.answer_key},
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


def _assessment_for_activity(
    activity: LearningActivity,
    section: CardSection | None,
) -> object:
    return LegacyQuizAdapter.from_json(
        activity_id=activity.id,
        objective=activity.objective,
        section_content=section.content_markdown if section else "",
        content=json.loads(activity.content_json or "{}"),
        answer_key=json.loads(activity.answer_key_json or "{}"),
    )


def _evaluator_factory(db: Session):
    # Preserve the old per-short-answer provider restoration behavior while
    # keeping objective-only submissions completely deterministic.
    def factory():
        return AssessmentAgent(restore_active_provider(db)).evaluate_short_answer

    return factory


async def run_post_assessment_hooks(
    db: Session,
    activity: LearningActivity,
    attempt: ActivityAttempt,
    card: KnowledgeCard | None,
    section: CardSection | None,
    *,
    allow_gap_diagnosis: bool = True,
) -> None:
    """Run mentor/gap hooks once, after the final assessment evidence exists."""
    result = json.loads(attempt.result_json or "{}")
    if result.get("postAssessmentHooksCompleted") or not card or not section:
        return
    effective_mastery, effective_score, effective_diagnostic = derive_effective_post_assessment(
        result, attempt.score, attempt.mastery_level, attempt.diagnostic_summary,
    )
    try:
        guidance = await TeacherAgent(restore_active_provider(db)).create_activity_followup(
            card.title, section.title, activity.objective or "", effective_score,
            effective_diagnostic,
        )
        db.add(TeacherGuidance(
            card_id=card.id, section_id=section.id, source_conversation_id=None,
            trigger="activity_result", content=guidance.content,
        ))
        db.commit()
    except Exception:
        logger.exception("activity mentor follow-up failed: activity_id=%s", activity.id)
    if should_run_activity_gap_diagnosis(result, allow_gap_diagnosis, effective_mastery):
        try:
            diagnosis = await SideAgent(restore_active_provider(db)).diagnose(
                "；".join(result.get("misconceptions", [])) or effective_diagnostic,
                context=(
                    f"知识卡：{card.title}\n章节：{section.title}"
                    f"\n课程内容：{section.content_markdown}"
                ),
            )
            if diagnosis.proposal:
                db.add(RelatedCardProposal(
                    conversation_id=None, activity_id=activity.id, card_id=card.id,
                    section_id=section.id, title=diagnosis.proposal.title,
                    reason=diagnosis.proposal.reason,
                    relation_type=diagnosis.proposal.relation_type,
                ))
                db.commit()
        except Exception:
            logger.exception("activity gap diagnosis failed: activity_id=%s", activity.id)
    result["postAssessmentHooksCompleted"] = True
    attempt.result_json = json.dumps(result, ensure_ascii=False)
    db.commit()
    db.refresh(attempt)


def derive_effective_post_assessment(
    result: dict,
    score: int | None,
    mastery: str | None,
    diagnostic: str | None,
) -> tuple[str, int, str]:
    """Derive hook-only feedback while preserving legacy attempt columns."""
    effective_mastery = result.get("postFollowUpMastery") or mastery or "needs_review"
    original_score = score or 0
    if effective_mastery == "mastered":
        effective_score = max(original_score, 85)
    elif effective_mastery == "developing":
        effective_score = max(original_score, 60)
    else:
        effective_score = original_score
    if result.get("postFollowUpMastery"):
        effective_diagnostic = (
            f"完成针对性追问后，当前掌握程度为：{effective_mastery}。"
        )
    else:
        effective_diagnostic = diagnostic or ""
    return effective_mastery, effective_score, effective_diagnostic


def should_run_activity_gap_diagnosis(
    result: dict,
    allow_gap_diagnosis: bool = True,
    effective_mastery: str | None = None,
) -> bool:
    """Only unresolved, permitted evidence can create a knowledge branch."""
    mastery = effective_mastery or result.get("postFollowUpMastery")
    return (
        allow_gap_diagnosis
        and not bool(result.get("lowConfidence"))
        and mastery == "needs_review"
    )


async def submit_attempt(
    db: Session,
    activity: LearningActivity,
    answers: dict,
) -> dict:
    if activity.status != "ready":
        raise HTTPException(status_code=409, detail="Learning activity is not ready")
    section = db.get(CardSection, activity.section_id)
    card = db.get(KnowledgeCard, activity.card_id)
    assessment = _assessment_for_activity(activity, section)
    service = AttemptSubmissionService(
        short_answer_evaluator_factory=_evaluator_factory(db),
    )
    submission = await service.submit(db, activity, assessment, answers)
    attempt = submission.attempt
    initial_result = json.loads(attempt.result_json or "{}")
    if attempt.status == "follow_up_pending":
        return activity_attempt_response(attempt)
    await run_post_assessment_hooks(
        db, activity, attempt, card, section,
        allow_gap_diagnosis=not initial_result.get("lowConfidence", False),
    )
    return activity_attempt_response(attempt)


async def submit_follow_up(
    db: Session,
    activity: LearningActivity,
    attempt: ActivityAttempt,
    answer: str,
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
            assessment, follow_up, answer, evaluator_factory(),
        )
    except Exception:
        logger.exception(
            "activity follow-up evaluation failed: activity_id=%s attempt_id=%s",
            activity.id,
            attempt.id,
        )
        # Do not mutate or commit: a retry sees the same pending follow-up.
        raise HTTPException(status_code=502, detail="Follow-up evaluation failed")

    # Only mutate after evaluation has fully succeeded. Keep private linkage in
    # result_json, but expose only the safe result projection.
    score = int(getattr(evaluation, "score", 0))
    follow_up["status"] = "completed"
    follow_up["answer"] = answer
    follow_up["result"] = {
        "score": score,
        "correct": score >= 60,
        "feedback": getattr(evaluation, "feedback", ""),
    }
    original_mastery = attempt.mastery_level or "needs_review"
    if score >= 60:
        follow_up_mastery = "mastered" if original_mastery == "mastered" else "developing"
    else:
        follow_up_mastery = original_mastery
    result["postFollowUpMastery"] = follow_up_mastery
    result["followUp"] = follow_up
    attempt.result_json = json.dumps(result, ensure_ascii=False)
    attempt.status = "evaluated"
    attempt.completed_at = now()
    db.commit()
    db.refresh(attempt)

    card = db.get(KnowledgeCard, activity.card_id)
    await run_post_assessment_hooks(db, activity, attempt, card, section)
    return activity_attempt_response(attempt)
