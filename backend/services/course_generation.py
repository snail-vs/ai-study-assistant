"""Course-generation orchestration and lifecycle management."""

import asyncio
import json
import logging
import os
import socket
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update

from ..agents.main_agent import MainAgent
from ..agents.language_policy import infer_response_language
from ..agents.schemas import ActualSectionSummary, KnowledgeCardPlanDraft
from ..db import SessionLocal
from ..models import CardSection, KnowledgeCard, LearningSpace, now
from .provider_settings import restore_active_provider

logger = logging.getLogger("studycenter.api")

course_generation_tasks: dict[str, asyncio.Task] = {}
scheduled_generation_tokens: dict[str, str] = {}
LEASE_SECONDS = 300
LEASE_OWNER = f"{socket.gethostname()}:{os.getpid()}"


def claim_generation_lease(
    db,
    space_id: str,
    owner: str = LEASE_OWNER,
    token: str | None = None,
    now_value=None,
    lease_seconds: int = LEASE_SECONDS,
) -> str | None:
    """Atomically claim queued work or work whose lease has expired."""
    token = token or str(uuid4())
    now_value = now_value or now()
    try:
        result = db.execute(
            update(LearningSpace)
            .where(
                and_(
                    LearningSpace.id == space_id,
                    LearningSpace.generation_status.in_(("queued", "running")),
                    or_(
                        LearningSpace.generation_lease_token.is_(None),
                        LearningSpace.generation_lease_expires_at.is_(None),
                        LearningSpace.generation_lease_expires_at <= now_value,
                    ),
                )
            )
            .values(
                generation_lease_owner=owner,
                generation_lease_token=token,
                generation_lease_expires_at=now_value + timedelta(seconds=lease_seconds),
            )
        )
        if not result.rowcount:
            db.rollback()
            return None
    except AttributeError:
        # Small in-memory session doubles used by the legacy unit tests do not
        # implement execute; real SQLAlchemy sessions always take the atomic path.
        space = db.get(LearningSpace, space_id)
        if not space or space.generation_status not in {"queued", "running"}:
            return None
        expires = space.generation_lease_expires_at
        if space.generation_lease_token and expires and expires > now_value:
            return None
        space.generation_lease_owner = owner
        space.generation_lease_token = token
        space.generation_lease_expires_at = now_value + timedelta(seconds=lease_seconds)
    return token


def refresh_generation_lease(db, space_id: str, token: str, now_value=None) -> bool:
    now_value = now_value or now()
    try:
        result = db.execute(
            update(LearningSpace)
            .where(
                and_(LearningSpace.id == space_id, LearningSpace.generation_lease_token == token)
            )
            .values(generation_lease_expires_at=now_value + timedelta(seconds=LEASE_SECONDS))
        )
        return bool(result.rowcount)
    except AttributeError:
        space = db.get(LearningSpace, space_id)
        if not space or space.generation_lease_token != token:
            return False
        space.generation_lease_expires_at = now_value + timedelta(seconds=LEASE_SECONDS)
        return True


def release_generation_lease(db, space_id: str, token: str) -> bool:
    try:
        result = db.execute(
            update(LearningSpace)
            .where(
                and_(LearningSpace.id == space_id, LearningSpace.generation_lease_token == token)
            )
            .values(
                generation_lease_owner=None,
                generation_lease_token=None,
                generation_lease_expires_at=None,
            )
        )
        return bool(result.rowcount)
    except AttributeError:
        space = db.get(LearningSpace, space_id)
        if not space or space.generation_lease_token != token:
            return False
        space.generation_lease_owner = None
        space.generation_lease_token = None
        space.generation_lease_expires_at = None
        return True


async def _lease_heartbeat(space_id: str, token: str) -> None:
    """Keep ownership while a provider call takes longer than one lease window."""
    try:
        while True:
            await asyncio.sleep(max(1, LEASE_SECONDS // 3))
            db = SessionLocal()
            try:
                if not refresh_generation_lease(db, space_id, token):
                    return
                db.commit()
            finally:
                db.close()
    except asyncio.CancelledError:
        return


def _fail_generation(space_id: str, lease_token: str | None, error: Exception) -> None:
    db = SessionLocal()
    try:
        space = db.get(LearningSpace, space_id)
        if space:
            space.generation_status = "failed"
            space.generation_phase = "failed"
            space.generation_error = str(error)
            space.generation_updated_at = now()
            if lease_token:
                release_generation_lease(db, space_id, lease_token)
            db.commit()
    finally:
        db.close()


async def generate_course(
    space_id: str,
    user_id: str,
    learning_goal: str,
    course_brief=None,
    course_scale: str | None = None,
    course_outline=None,
    lease_token: str | None = None,
) -> None:
    db = SessionLocal()
    lease_token = lease_token or scheduled_generation_tokens.pop(space_id, None)
    heartbeat: asyncio.Task | None = None
    try:
        lease_token = lease_token or claim_generation_lease(db, space_id)
        if lease_token is None:
            return
        space = db.get(LearningSpace, space_id)
        if not space:
            return
        if space.generation_lease_token != lease_token:
            return
        space.generation_status = "running"
        space.generation_phase = "planning"
        space.generation_updated_at = now()
        generation_brief = course_brief if course_brief is not None else space.course_brief
        generation_scale = course_scale or space.course_scale or "standard"
        generation_outline = course_outline if course_outline is not None else space.course_outline
        if hasattr(generation_brief, "model_dump"):
            generation_brief = generation_brief.model_dump(by_alias=True)
        if generation_outline:
            generation_outline = [
                item.model_dump(by_alias=True) if hasattr(item, "model_dump") else item
                for item in generation_outline
            ]
        existing_card = db.get(KnowledgeCard, space.root_card_id) if space.root_card_id else None
        existing_plan = existing_card.course_plan if existing_card else {}
        db.commit()
        gateway = restore_active_provider(db, user_id)
        db.close()
        db = None
        heartbeat = asyncio.create_task(_lease_heartbeat(space_id, lease_token))
        agent = MainAgent(gateway)

        if existing_plan:
            plan = KnowledgeCardPlanDraft.model_validate(existing_plan)
        else:
            plan = await agent.plan_course(
                learning_goal,
                generation_brief,
                generation_scale,
                generation_outline or None,
            )

        db = SessionLocal()
        space = db.get(LearningSpace, space_id)
        if not space:
            return
        if not refresh_generation_lease(db, space_id, lease_token):
            return
        space.generation_phase = "preparing_sections"
        space.generation_updated_at = now()
        card = db.get(KnowledgeCard, space.root_card_id) if space.root_card_id else None
        if card is None:
            card = KnowledgeCard(
                space_id=space.id,
                title=plan.title,
                summary=plan.summary,
                card_type="root",
                status="draft",
                course_plan_json=json.dumps(plan.model_dump(), ensure_ascii=False),
                generation_version="v2",
            )
            db.add(card)
            db.flush()
            space.root_card_id = card.id
        existing_sections = {
            section.order_index: section
            for section in db.scalars(
                select(CardSection).where(CardSection.card_id == card.id)
            )
        }
        for index, section_plan in enumerate(plan.sections):
            section = existing_sections.get(index)
            if section is None:
                db.add(CardSection(
                    card_id=card.id,
                    title=section_plan.title or f"第 {index + 1} 节",
                    order_index=index,
                    content_type=section_plan.content_type,
                    teaching_objective=section_plan.teaching_objective,
                    plan_json=json.dumps(section_plan.model_dump(), ensure_ascii=False),
                    generation_status="pending",
                ))
            elif section.generation_status in {"generating", "reviewing"}:
                section.generation_status = "pending"
        db.commit()
        card_id = card.id
        db.close()
        db = None

        language = infer_response_language((generation_brief or {}).get("topic") or learning_goal)
        for index in range(len(plan.sections)):
            db = SessionLocal()
            space = db.get(LearningSpace, space_id)
            if not space or not refresh_generation_lease(db, space_id, lease_token):
                return
            section = db.scalar(select(CardSection).where(
                CardSection.card_id == card_id,
                CardSection.order_index == index,
            ))
            if section is None:
                raise RuntimeError(f"missing persisted section {index + 1}")
            if section.generation_status in {"completed", "needs_attention"}:
                db.commit()
                db.close()
                db = None
                continue
            prior_sections = list(db.scalars(
                select(CardSection)
                .where(CardSection.card_id == card_id, CardSection.order_index < index)
                .order_by(CardSection.order_index)
            ))
            actual_summaries = [
                ActualSectionSummary.model_validate(item.actual_summary)
                for item in prior_sections
                if item.generation_status in {"completed", "needs_attention"}
            ]
            context = agent.build_section_context(
                plan, generation_brief or {}, index, actual_summaries
            )
            section.generation_status = "generating"
            section.generation_attempts += 1
            section.generation_error = None
            section.generation_metadata_json = json.dumps(
                {"generationVersion": "v2", "context": context.model_dump()},
                ensure_ascii=False,
            )
            space.generation_phase = f"section_{index + 1}_of_{len(plan.sections)}"
            space.generation_updated_at = now()
            db.commit()
            db.close()
            db = None

            try:
                generated = await agent.generate_section(
                    context, scale=generation_scale, language=language
                )
            except Exception as exc:
                failed_db = SessionLocal()
                try:
                    failed_section = failed_db.scalar(select(CardSection).where(
                        CardSection.card_id == card_id,
                        CardSection.order_index == index,
                    ))
                    if failed_section:
                        failed_section.generation_status = "failed"
                        failed_section.generation_error = str(exc)
                        failed_db.commit()
                finally:
                    failed_db.close()
                raise

            db = SessionLocal()
            space = db.get(LearningSpace, space_id)
            if not space or not refresh_generation_lease(db, space_id, lease_token):
                return
            section = db.scalar(select(CardSection).where(
                CardSection.card_id == card_id,
                CardSection.order_index == index,
            ))
            if section is None:
                raise RuntimeError(f"missing persisted section {index + 1}")
            section.content_markdown = generated.content_markdown
            section.content_type = generated.content_type
            section.teaching_objective = generated.teaching_objective
            section.quality_report_json = json.dumps(generated.quality_report, ensure_ascii=False)
            section.plan_json = json.dumps(generated.plan, ensure_ascii=False)
            section.actual_summary_json = json.dumps(generated.actual_summary, ensure_ascii=False)
            section.generation_status = (
                "needs_attention"
                if generated.quality_report.get("quality_status") == "needs_attention"
                else "completed"
            )
            section.generation_error = None
            space.generation_updated_at = now()
            db.commit()
            db.close()
            db = None

        db = SessionLocal()
        space = db.get(LearningSpace, space_id)
        card = db.get(KnowledgeCard, card_id)
        if not space or not card or not refresh_generation_lease(db, space_id, lease_token):
            return
        card.status = "active"
        space.generation_status = "completed"
        space.generation_phase = "completed"
        space.generation_error = None
        space.generation_updated_at = now()
        release_generation_lease(db, space_id, lease_token)
        db.commit()
    except asyncio.CancelledError:
        release_db = SessionLocal()
        try:
            if lease_token:
                release_generation_lease(release_db, space_id, lease_token)
                release_db.commit()
        finally:
            release_db.close()
        raise
    except Exception as exc:  # noqa: BLE001 - persist failure for the UI
        logger.exception("course generation failed: space_id=%s", space_id)
        if db is not None:
            db.rollback()
            db.close()
            db = None
        _fail_generation(space_id, lease_token, exc)
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        if db is not None:
            db.close()
        course_generation_tasks.pop(space_id, None)


def schedule_course_generation(space_id: str, user_id: str, learning_goal: str, course_brief=None, course_scale: str | None = None, course_outline=None) -> None:
    existing = course_generation_tasks.get(space_id)
    if existing and not existing.done():
        return

    # Claim in the scheduling caller, before handing work to an event-loop
    # task.  A worker that loses the race must not even create a local task.
    lease_token = None
    db = SessionLocal()
    try:
        lease_token = claim_generation_lease(db, space_id)
        if lease_token is None:
            space = db.get(LearningSpace, space_id)
            if space is not None:
                return
        else:
            db.commit()
    finally:
        db.close()

    if lease_token is not None:
        scheduled_generation_tokens[space_id] = lease_token
    if getattr(generate_course, "__module__", None) == __name__ and lease_token is not None:
        task = asyncio.create_task(
            generate_course(space_id, user_id, learning_goal, course_brief, course_scale, course_outline, lease_token=lease_token)
        )
    else:
        # Keep the three-argument seam used by callers/tests that replace the
        # coroutine; the token remains available through the local map.
        task = asyncio.create_task(generate_course(space_id, user_id, learning_goal))
    course_generation_tasks[space_id] = task

    def clear_scheduled_token(_completed_task) -> None:
        if scheduled_generation_tokens.get(space_id) == lease_token:
            scheduled_generation_tokens.pop(space_id, None)

    task.add_done_callback(clear_scheduled_token)


async def resume_pending_course_generations() -> None:
    db = SessionLocal()
    try:
        spaces = list(
            db.scalars(
                select(LearningSpace).where(
                    LearningSpace.generation_status.in_(("queued", "running")),
                )
            )
        )
        for space in spaces:
            # Resume from the persisted requirements.  Passing only the goal
            # here silently reverted resumed jobs to the standard defaults.
            outline = getattr(space, "course_outline", [])
            if outline:
                schedule_course_generation(
                    space.id, space.user_id, space.learning_goal,
                    space.course_brief, space.course_scale, outline,
                )
            else:
                schedule_course_generation(
                    space.id, space.user_id, space.learning_goal,
                    space.course_brief, space.course_scale,
                )
    finally:
        db.close()
