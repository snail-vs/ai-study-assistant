"""Post-assessment mentor guidance and knowledge-gap hooks."""

import json
import logging

from ..agents.side_agent import SideAgent
from ..agents.teacher_agent import TeacherAgent
from ..models import (
    ActivityAttempt,
    CardSection,
    KnowledgeCard,
    LearningActivity,
    RelatedCardProposal,
    TeacherGuidance,
)
from .provider_settings import restore_active_provider

logger = logging.getLogger("studycenter.activity")


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


async def run_post_assessment_hooks(
    db, activity: LearningActivity, attempt: ActivityAttempt,
    card: KnowledgeCard | None, section: CardSection | None,
    *, allow_gap_diagnosis: bool = True,
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
            card.title,
            section.title,
            activity.objective or "",
            effective_score,
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
                context=(f"知识卡：{card.title}\n章节：{section.title}"
                         f"\n课程内容：{section.content_markdown}"),
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
