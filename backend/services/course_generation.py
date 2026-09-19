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


async def generate_course(
    space_id: str,
    user_id: str,
    learning_goal: str,
    course_brief=None,
    course_scale: str | None = None,
    lease_token: str | None = None,
) -> None:
    db = SessionLocal()
    initial_db = db
    lease_token = lease_token or scheduled_generation_tokens.pop(space_id, None)
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
        space.generation_phase = "generating"
        space.generation_updated_at = now()
        generation_brief = course_brief if course_brief is not None else space.course_brief
        generation_scale = course_scale or space.course_scale or "standard"
        db.commit()
        gateway = restore_active_provider(db, user_id)
        db.close()
        db = None

        draft = await MainAgent(gateway).create_card(learning_goal, generation_brief, generation_scale)

        db = SessionLocal()
        space = db.get(LearningSpace, space_id)
        if not space:
            return
        if not refresh_generation_lease(db, space_id, lease_token):
            return
        space.generation_phase = "saving"
        space.generation_updated_at = now()
        db.commit()
        card = KnowledgeCard(
            space_id=space.id, title=draft.title, card_type="root", status="active"
        )
        db.add(card)
        db.flush()
        for index, section in enumerate(draft.sections):
            db.add(
                CardSection(
                    card_id=card.id,
                    title=section.title or f"第 {index + 1} 节",
                    order_index=index,
                    content_markdown=section.content_markdown,
                    content_type=section.content_type,
                    teaching_objective=section.teaching_objective,
                    quality_report_json=json.dumps(section.quality_report, ensure_ascii=False),
                )
            )
        space.root_card_id = card.id
        space.generation_status = "completed"
        space.generation_phase = "completed"
        space.generation_error = None
        space.generation_updated_at = now()
        release_generation_lease(db, space_id, lease_token)
        db.commit()
    except asyncio.CancelledError:
        release_db = db
        should_close = False
        if release_db is None:
            release_db = SessionLocal()
            should_close = True
        if lease_token:
            release_generation_lease(release_db, space_id, lease_token)
            release_db.commit()
        if should_close and release_db is not initial_db:
            release_db.close()
        raise
    except Exception as exc:  # noqa: BLE001 - persist failure for the UI
        logger.exception("course generation failed: space_id=%s", space_id)
        if db is not None:
            db.rollback()
            space = db.get(LearningSpace, space_id)
        else:
            db = SessionLocal()
            space = db.get(LearningSpace, space_id)
        if space:
            space.generation_status = "failed"
            space.generation_phase = "failed"
            space.generation_error = str(exc)
            space.generation_updated_at = now()
            release_generation_lease(db, space_id, lease_token)
            db.commit()
    finally:
        if db is not None:
            db.close()
        course_generation_tasks.pop(space_id, None)


def schedule_course_generation(space_id: str, user_id: str, learning_goal: str, course_brief=None, course_scale: str | None = None) -> None:
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
            generate_course(space_id, user_id, learning_goal, course_brief, course_scale, lease_token=lease_token)
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
            schedule_course_generation(
                space.id,
                space.user_id,
                space.learning_goal,
                space.course_brief,
                space.course_scale,
            )
    finally:
        db.close()
