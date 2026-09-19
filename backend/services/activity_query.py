"""Learning activity lookup and safe public response projections."""

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ActivityAttempt, CardSection, KnowledgeCard, LearningActivity, LearningSpace
from ..security.auth import current_user_id


def _compatibility_module():
    import sys
    return sys.modules.get(__name__.rsplit(".", 1)[0] + "." + "activity_" + "workflow")


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
        results.append({key: item[key] for key in (
            "questionId", "correct", "score", "feedback", "referenceAnswer",
            "errorType", "confidence", "missingRubricId",
        ) if key in item})
    return {
        "id": attempt.id, "activityId": attempt.activity_id, "status": attempt.status,
        "score": attempt.score, "masteryLevel": attempt.mastery_level,
        "diagnosticSummary": attempt.diagnostic_summary, "results": results,
        "createdAt": attempt.created_at, "completedAt": attempt.completed_at,
        "followUp": public_follow_up, "postFollowUpMastery": result.get("postFollowUpMastery"),
    }


def activity_response(activity: LearningActivity, attempt: ActivityAttempt | None = None) -> dict:
    content = json.loads(activity.content_json or "{}")
    compatibility = _compatibility_module()
    projector = getattr(compatibility, "activity_attempt_response", activity_attempt_response)
    return {
        "id": activity.id, "cardId": activity.card_id, "sectionId": activity.section_id,
        "activityType": activity.activity_type, "title": activity.title,
        "objective": activity.objective, "status": activity.status,
        "questions": content.get("questions", []),
        "latestAttempt": projector(attempt), "createdAt": activity.created_at,
    }


def get_activity(activity_id: str, db: Session) -> LearningActivity:
    compatibility = _compatibility_module()
    user_id = getattr(compatibility, "current_user_id", current_user_id)()
    activity = db.scalar(
        select(LearningActivity)
        .join(KnowledgeCard, LearningActivity.card_id == KnowledgeCard.id)
        .join(LearningSpace, KnowledgeCard.space_id == LearningSpace.id)
        .where(LearningActivity.id == activity_id, LearningSpace.user_id == user_id)
    )
    section = db.get(CardSection, activity.section_id) if activity else None
    card = db.get(KnowledgeCard, activity.card_id) if activity else None
    if not activity or not section or not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Learning activity not found")
    return activity
