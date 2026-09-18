import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agents.bridge_agent import BridgeAgent
from .agents.assessment_agent import AssessmentAgent
from .agents.main_agent import MainAgent
from .agents.side_agent import SideAgent
from .agents.teacher_agent import TeacherAgent
from .agents.prompts import QA_TUTOR_SYSTEM
from .agents.registry import default_participants, get_agent, AGENTS
from .assessment import AttemptSubmissionService, LegacyQuizAdapter
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
    ActivityAttempt,
    LearningActivity,
    RelatedCardProposal,
    TeacherGuidance,
)
from .schemas import (
    ConversationResponse,
    CreateKnowledgeCardRequest,
    CreateConversationRequest,
    CreateMessageRequest,
    CreateNoteRequest,
    LearningRuntimeResponse,
    UpdateLearningRuntimeRequest,
    KnowledgeCardResponse,
    MessageResponse,
    NoteResponse,
    UpdateNoteRequest,
    AgentDefinitionResponse,
    AIRunResponse,
    RelatedCardProposalResponse,
    ActivityAttemptResponse,
    LearningActivityResponse,
    SubmitActivityAttemptRequest,
    SubmitActivityFollowUpRequest,
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


def _activity_attempt_response(attempt: ActivityAttempt | None) -> dict | None:
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


def _activity_response(activity: LearningActivity, attempt: ActivityAttempt | None = None) -> dict:
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
        "latestAttempt": _activity_attempt_response(attempt),
        "createdAt": activity.created_at,
    }


def _get_activity(activity_id: str, db: Session) -> LearningActivity:
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


async def _run_activity_post_assessment_hooks(
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
    if card and section:
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
                context=f"知识卡：{card.title}\n章节：{section.title}\n课程内容：{section.content_markdown}",
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
        effective_diagnostic = f"完成针对性追问后，当前掌握程度为：{effective_mastery}。"
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
    return allow_gap_diagnosis and not bool(result.get("lowConfidence")) and mastery == "needs_review"


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
    activities = list(db.scalars(
        select(LearningActivity)
        .where(LearningActivity.card_id == card_id, LearningActivity.section_id == section_id)
        .order_by(LearningActivity.created_at)
    ))
    return [_activity_response(activity, db.scalar(
        select(ActivityAttempt).where(ActivityAttempt.activity_id == activity.id)
        .order_by(ActivityAttempt.created_at.desc())
    )) for activity in activities]


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
    activity = db.scalar(select(LearningActivity).where(
        LearningActivity.section_id == section_id,
        LearningActivity.activity_type == "quiz",
    ))
    if activity and activity.status == "ready":
        attempt = db.scalar(select(ActivityAttempt).where(ActivityAttempt.activity_id == activity.id).order_by(ActivityAttempt.created_at.desc()))
        return _activity_response(activity, attempt)
    if activity is None:
        activity = LearningActivity(
            card_id=card_id,
            section_id=section_id,
            activity_type="quiz",
            title="理解检查",
            objective=section.teaching_objective or f"检查是否理解“{section.title}”的核心内容。",
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
            {"version": 1, "questions": [item.model_dump(mode="json") for item in draft.questions]},
            ensure_ascii=False,
        )
        activity.answer_key_json = json.dumps(
            {item.question_id: item.model_dump(mode="json", by_alias=True) for item in draft.answer_key},
            ensure_ascii=False,
        )
        activity.status = "ready"
        db.commit()
        db.refresh(activity)
        return _activity_response(activity)
    except Exception as exc:
        activity.status = "failed"
        activity.generation_error = str(exc)
        db.commit()
        raise


@router.get("/activities/{activity_id}", response_model=LearningActivityResponse)
def get_learning_activity(activity_id: str, db: Session = Depends(get_db)):
    activity = _get_activity(activity_id, db)
    attempt = db.scalar(select(ActivityAttempt).where(ActivityAttempt.activity_id == activity.id).order_by(ActivityAttempt.created_at.desc()))
    return _activity_response(activity, attempt)


@router.get("/activities/{activity_id}/attempts/latest", response_model=ActivityAttemptResponse | None)
def get_latest_activity_attempt(activity_id: str, db: Session = Depends(get_db)):
    activity = _get_activity(activity_id, db)
    attempt = db.scalar(select(ActivityAttempt).where(ActivityAttempt.activity_id == activity.id).order_by(ActivityAttempt.created_at.desc()))
    return _activity_attempt_response(attempt)


@router.post("/activities/{activity_id}/attempts", response_model=ActivityAttemptResponse)
async def submit_activity_attempt(
    activity_id: str,
    payload: SubmitActivityAttemptRequest,
    db: Session = Depends(get_db),
):
    activity = _get_activity(activity_id, db)
    if activity.status != "ready":
        raise HTTPException(status_code=409, detail="Learning activity is not ready")
    section = db.get(CardSection, activity.section_id)
    card = db.get(KnowledgeCard, activity.card_id)
    assessment = LegacyQuizAdapter.from_json(
        activity_id=activity.id,
        objective=activity.objective,
        section_content=section.content_markdown if section else "",
        content=json.loads(activity.content_json or "{}"),
        answer_key=json.loads(activity.answer_key_json or "{}"),
    )
    def short_answer_evaluator_factory():
        # Preserve the old per-short-answer provider restoration behavior while
        # keeping objective-only submissions completely deterministic.
        return AssessmentAgent(restore_active_provider(db)).evaluate_short_answer

    service = AttemptSubmissionService(short_answer_evaluator_factory=short_answer_evaluator_factory)
    submission = await service.submit(db, activity, assessment, payload.answers)
    attempt = submission.attempt
    evaluation = submission.evaluation
    # A pending follow-up defers mentor and knowledge-gap hooks until the
    # learner completes that same attempt.
    initial_result = json.loads(attempt.result_json or "{}")
    if attempt.status == "follow_up_pending":
        return _activity_attempt_response(attempt)
    await _run_activity_post_assessment_hooks(
        db, activity, attempt, card, section,
        allow_gap_diagnosis=not initial_result.get("lowConfidence", False),
    )
    return _activity_attempt_response(attempt)


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
    activity = _get_activity(activity_id, db)
    attempt = db.get(ActivityAttempt, attempt_id)
    if not attempt or attempt.activity_id != activity.id:
        raise HTTPException(status_code=404, detail="Activity attempt not found")
    result = json.loads(attempt.result_json or "{}")
    follow_up = result.get("followUp")
    if not isinstance(follow_up, dict):
        raise HTTPException(status_code=409, detail="This attempt has no follow-up")
    if follow_up.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Follow-up has already been submitted")
    section = db.get(CardSection, activity.section_id)
    content = json.loads(activity.content_json or "{}")
    answer_key = json.loads(activity.answer_key_json or "{}")
    assessment = LegacyQuizAdapter.from_json(
        activity_id=activity.id,
        objective=activity.objective,
        section_content=section.content_markdown if section else "",
        content=content,
        answer_key=answer_key,
    )

    def short_answer_evaluator_factory():
        return AssessmentAgent(restore_active_provider(db)).evaluate_short_answer

    service = AttemptSubmissionService(short_answer_evaluator_factory=short_answer_evaluator_factory)
    try:
        evaluation = await service.evaluate_follow_up(
            assessment, follow_up, payload.answer, short_answer_evaluator_factory()
        )
    except Exception:
        logger.exception("activity follow-up evaluation failed: activity_id=%s attempt_id=%s", activity.id, attempt.id)
        # Do not mutate or commit: a retry sees the same pending follow-up.
        raise HTTPException(status_code=502, detail="Follow-up evaluation failed")

    # Only mutate after evaluation has fully succeeded.  Keep private linkage
    # in result_json, but expose only the safe result projection.
    score = int(getattr(evaluation, "score", 0))
    follow_up["status"] = "completed"
    follow_up["answer"] = payload.answer
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
    # Reuse the existing post-assessment behavior only after the follow-up is
    # complete.  The helper's marker prevents duplicate hooks.
    await _run_activity_post_assessment_hooks(db, activity, attempt, card, section)
    return _activity_attempt_response(attempt)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(conversation_id: str, db: Session = Depends(get_db)):
    owned_conversation(db, conversation_id)
    conversation = db.get(Conversation, conversation_id)
    card = db.get(KnowledgeCard, conversation.card_id) if conversation else None
    if not conversation or not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Conversation not found")
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
    )


@router.get("/conversations/{conversation_id}/runs/active", response_model=AIRunResponse | None)
def get_active_run(conversation_id: str, db: Session = Depends(get_db)):
    owned_conversation(db, conversation_id)
    run = db.scalar(
        select(AIRun)
        .where(AIRun.conversation_id == conversation_id, AIRun.status.in_(("queued", "running")))
        .order_by(AIRun.created_at.desc())
    )
    if run and run.updated_at and (now() - run.updated_at).total_seconds() > 180:
        run.status = "expired"
        run.phase = "expired"
        run.error_message = "AI 请求可能已中断，请重新发送。"
        db.commit()
    return run


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(conversation_id: str, payload: CreateMessageRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    owned_conversation(db, conversation_id)
    conversation = db.get(Conversation, conversation_id)
    card = db.get(KnowledgeCard, conversation.card_id) if conversation else None
    if not conversation or not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not conversation.section_id:
        raise HTTPException(status_code=409, detail="Legacy course-level conversations cannot receive section messages")
    if payload.section_id != conversation.section_id:
        raise HTTPException(status_code=409, detail="Conversation belongs to a different section")
    active_run = db.scalar(
        select(AIRun)
        .where(AIRun.conversation_id == conversation_id, AIRun.status.in_(("queued", "running")))
        .order_by(AIRun.created_at.desc())
    )
    if active_run:
        raise HTTPException(status_code=409, detail="该问题讨论正在处理上一条消息，请稍候")

    primary_agent_id = conversation.participant_ids[0] if conversation.participant_ids else (
        "teacher" if conversation.conversation_type == "main" else "side_tutor"
    )
    primary_agent = get_agent(primary_agent_id)
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        sender_id="user",
        sender_name="你",
        sender_role="user",
        visibility="user",
        content=payload.content,
    )
    db.add(user_message)
    run = AIRun(conversation_id=conversation_id, run_type="side_message", status="running", phase="waiting")
    db.add(run)
    db.commit()

    async def events() -> AsyncIterator[str]:
        message_id = str(uuid4())
        yield f"event: run.started\ndata: {json.dumps({'conversationId': conversation_id, 'runId': run.id, 'phase': 'waiting', 'label': '正在等待 AI 响应'}, ensure_ascii=False)}\n\n"
        yield f"event: message.started\ndata: {json.dumps({'conversationId': conversation_id, 'messageId': message_id, 'senderId': primary_agent_id, 'senderName': primary_agent.name if primary_agent else primary_agent_id, 'senderRole': primary_agent.role if primary_agent else 'assistant'}, ensure_ascii=False)}\n\n"
        answer_section = db.get(CardSection, conversation.section_id) if conversation.section_id else None
        messages = [{"role": "system", "content": QA_TUTOR_SYSTEM}]
        answer_context = ""
        if answer_section:
            answer_context = (
                f"当前知识卡：{card.title}\n当前章节：{answer_section.title}\n"
                f"课程内容：{answer_section.content_markdown[:6000]}"
            )
            messages.append({
                "role": "system",
                "content": answer_context,
            })
        try:
            yield f"event: run.phase\ndata: {json.dumps({'phase': 'planning', 'label': '正在理解问题并组织回答'}, ensure_ascii=False)}\n\n"
            run.phase = "planning"
            db.commit()
            answer_plan = await SideAgent(restore_active_provider(db)).plan_answer(
                payload.content,
                context=answer_context,
            )
            length_budget = {"short": "80～200", "medium": "200～400", "long": "400～700"}[answer_plan.target_length]
            messages.append({
                "role": "system",
                "content": (
                    "请严格依据下面的回答计划作答，不要扩展计划之外的背景知识。\n"
                    f"回答类型：{answer_plan.intent}\n直接答案：{answer_plan.direct_answer}\n"
                    f"必要要点：{json.dumps(answer_plan.key_points, ensure_ascii=False)}\n"
                    f"是否需要例子：{'是' if answer_plan.needs_example else '否'}\n"
                    f"目标长度：{length_budget} 个中文字符。"
                ),
            })
        except Exception:
            logger.exception("side answer planning failed; falling back to direct answer")
        yield f"event: run.phase\ndata: {json.dumps({'phase': 'answering', 'label': '答疑助教正在回答'}, ensure_ascii=False)}\n\n"
        run.phase = "answering"
        db.commit()
        if conversation.root_question:
            messages.append({"role": "system", "content": f"本讨论的起始问题：{conversation.root_question}"})
        history = list(db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.visibility == "user")
            .order_by(Message.created_at, Message.id)
        ))[-8:]
        messages.extend({"role": item.role, "content": item.content} for item in history)
        response_parts: list[str] = []
        try:
            async for delta in restore_active_provider(db).stream_text(messages, task="side_answer"):
                response_parts.append(delta)
                yield f"event: message.delta\ndata: {json.dumps({'messageId': message_id, 'senderId': primary_agent_id, 'delta': delta}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            # Keep text already received before a provider/parser failure. This
            # makes a partially streamed answer available after a refresh.
            if response_parts:
                db.add(Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    sender_id=primary_agent_id,
                    sender_name=primary_agent.name if primary_agent else primary_agent_id,
                    sender_role=primary_agent.role if primary_agent else "assistant",
                    visibility="user",
                    content="".join(response_parts),
                ))
                db.commit()
            run.status = "failed"
            run.phase = "answering"
            run.error_message = str(exc)
            db.commit()
            message = str(exc)
            if "MissingSessionID" in message or "only be used in OpenCode" in message:
                message = "OpenCode 免费模型只能在 OpenCode 会话中使用，请改用 OpenCode 付费模型、DeepSeek 或 OpenRouter 模型。"
            yield f"event: run.failed\ndata: {json.dumps({'code': 'AI_PROVIDER_ERROR', 'message': message}, ensure_ascii=False)}\n\n"
            yield "event: message.completed\ndata: {}\n\n"
            return
        assistant = Message(
            conversation_id=conversation_id,
            role="assistant",
            sender_id=primary_agent_id,
            sender_name=primary_agent.name if primary_agent else primary_agent_id,
            sender_role=primary_agent.role if primary_agent else "assistant",
            visibility="user",
            content="".join(response_parts),
        )
        db.add(assistant)
        db.commit()
        try:
            # 每次答疑后都由课程导师做一次归位，帮助学生回到当前章节。
            # 这一步不依赖知识断层诊断；诊断只负责后续的推荐知识卡。
            section = db.get(CardSection, conversation.section_id) if conversation.section_id else None
            source_card = db.get(KnowledgeCard, conversation.card_id) if section else None
            if not section or not source_card or section.card_id != conversation.card_id:
                logger.warning(
                    "skip teacher guidance: conversation_id=%s card_id=%s conversation_section_id=%s payload_section_id=%s",
                    conversation.id,
                    conversation.card_id,
                    conversation.section_id,
                    payload.section_id,
                )
            if section and source_card and section.card_id == conversation.card_id:
                try:
                    yield f"event: run.phase\ndata: {json.dumps({'phase': 'guiding', 'label': '课程导师正在引导归位'}, ensure_ascii=False)}\n\n"
                    run.phase = "guiding"
                    db.commit()
                    guidance_draft = await TeacherAgent(restore_active_provider(db)).create_side_followup(
                        source_card.title,
                        section.title,
                        section.content_markdown,
                        payload.content,
                        "".join(response_parts),
                    )
                    guidance = TeacherGuidance(
                        card_id=conversation.card_id,
                        section_id=section.id,
                        source_conversation_id=conversation.id,
                        source_question_message_id=user_message.id,
                        source_answer_message_id=assistant.id,
                        source_question=payload.content,
                        trigger="side_question",
                        content=guidance_draft.content,
                    )
                    db.add(guidance)
                    db.commit()
                    db.refresh(guidance)
                    yield f"event: guidance.updated\ndata: {json.dumps(TeacherGuidanceResponse.model_validate(guidance).model_dump(by_alias=True), default=str, ensure_ascii=False)}\n\n"
                except Exception as exc:
                    logger.exception(
                        "teacher guidance failed: conversation_id=%s card_id=%s section_id=%s",
                        conversation.id,
                        conversation.card_id,
                        section.id,
                    )
                    yield f"event: guidance.failed\ndata: {json.dumps({'code': 'TEACHER_GUIDANCE_FAILED', 'message': str(exc)}, ensure_ascii=False)}\n\n"

            yield f"event: run.phase\ndata: {json.dumps({'phase': 'diagnosing', 'label': '正在分析你的知识断层'}, ensure_ascii=False)}\n\n"
            run.phase = "diagnosing"
            db.commit()
            diagnosis = await SideAgent(restore_active_provider(db)).diagnose(
                payload.content,
                context=(
                    f"知识卡：{source_card.title}\n章节：{section.title}\n课程内容：{section.content_markdown}"
                    if section and source_card else ""
                ),
            )
            logger.info(
                "side-agent diagnosis: conversation_id=%s has_knowledge_gap=%s missing_topics=%s proposal=%s",
                conversation.id,
                diagnosis.diagnosis.has_knowledge_gap,
                diagnosis.diagnosis.missing_topics,
                diagnosis.proposal.title if diagnosis.proposal else None,
            )
            if diagnosis.diagnosis.has_knowledge_gap or diagnosis.proposal:
                yield f"event: diagnosis.updated\ndata: {json.dumps(diagnosis.diagnosis.model_dump(by_alias=True), ensure_ascii=False)}\n\n"
                if diagnosis.proposal:
                    yield f"event: run.phase\ndata: {json.dumps({'phase': 'recommending', 'label': '正在整理相关学习建议'}, ensure_ascii=False)}\n\n"
                    proposal = diagnosis.proposal.model_dump()
                    stored = RelatedCardProposal(
                        conversation_id=conversation_id,
                        card_id=conversation.card_id,
                        section_id=conversation.section_id,
                        title=proposal["title"],
                        reason=proposal["reason"],
                        relation_type=proposal["relation_type"],
                    )
                    db.add(stored)
                    db.commit()
                    proposal["proposalId"] = stored.id
                    proposal["relationType"] = proposal.pop("relation_type")
                    yield f"event: related_card.proposed\ndata: {json.dumps(proposal, ensure_ascii=False)}\n\n"
        except Exception as exc:
            run.status = "failed"
            run.phase = "diagnosing"
            run.error_message = str(exc)
            db.commit()
            yield f"event: run.failed\ndata: {json.dumps({'code': 'AI_DIAGNOSIS_FAILED', 'message': str(exc)})}\n\n"
        if run.status != "failed":
            run.status = "completed"
            run.phase = "completed"
            db.commit()
        yield f"event: run.completed\ndata: {json.dumps({'conversationId': conversation_id}, ensure_ascii=False)}\n\n"
        yield "event: message.completed\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


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
