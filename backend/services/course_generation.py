"""Course-generation orchestration and lifecycle management."""

import asyncio
import json
import logging

from sqlalchemy import select

from ..agents.main_agent import MainAgent
from ..db import SessionLocal
from ..models import CardSection, KnowledgeCard, LearningSpace, now
from .provider_settings import restore_active_provider

logger = logging.getLogger("studycenter.api")

course_generation_tasks: dict[str, asyncio.Task] = {}


async def generate_course(space_id: str, user_id: str, learning_goal: str) -> None:
    db = SessionLocal()
    try:
        space = db.get(LearningSpace, space_id)
        if not space:
            return
        space.generation_status = "running"
        space.generation_phase = "generating"
        space.generation_updated_at = now()
        db.commit()
        gateway = restore_active_provider(db, user_id)
        db.close()
        db = None

        draft = await MainAgent(gateway).create_card(learning_goal)

        db = SessionLocal()
        space = db.get(LearningSpace, space_id)
        if not space:
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
        db.commit()
    except asyncio.CancelledError:
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
            db.commit()
    finally:
        if db is not None:
            db.close()
        course_generation_tasks.pop(space_id, None)


def schedule_course_generation(space_id: str, user_id: str, learning_goal: str) -> None:
    existing = course_generation_tasks.get(space_id)
    if existing and not existing.done():
        return
    course_generation_tasks[space_id] = asyncio.create_task(
        generate_course(space_id, user_id, learning_goal)
    )


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
            schedule_course_generation(space.id, space.user_id, space.learning_goal)
    finally:
        db.close()
