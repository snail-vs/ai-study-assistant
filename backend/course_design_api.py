"""Course-design intake routes."""

from fastapi import APIRouter, Depends, HTTPException

from .agents.course_intake_agent import CourseIntakeAgent
from .agents.outline_agent import CourseOutlineAgent
from .db import get_db
from .schemas import (
    CourseBrief,
    CourseDesignTurnRequest,
    CourseDesignTurnResponse,
    CourseOutlineItem,
    CourseOutlineRequest,
    CourseOutlineResponse,
    CourseOutlineRevisionRequest,
    CourseOutlineRevisionResponse,
)
from .security.auth import current_user_id, require_current_user
from .services.provider_settings import restore_active_provider

router = APIRouter(dependencies=[Depends(require_current_user)])


@router.post("/course-design/turn", response_model=CourseDesignTurnResponse)
async def course_design_turn(payload: CourseDesignTurnRequest, db=Depends(get_db)):
    user_messages = [message for message in payload.messages if message.role == "user"]
    turn = min(len(user_messages), 3)
    brief = payload.brief or CourseBrief()
    scale = payload.course_scale
    gateway = restore_active_provider(db, current_user_id())
    result = await CourseIntakeAgent(gateway).turn(
        [message.model_dump() for message in payload.messages],
        brief.model_dump(by_alias=True),
        scale,
    )
    if payload.skip or turn >= 3:
        result.ready = True
        result.question = None
        result.quick_options = []
        result.assistant_message = result.assistant_message or "好的，我会按当前信息直接为你设计课程。"
    normalized = CourseBrief.model_validate(result.brief)
    normalized_scale = result.recommended_scale if result.recommended_scale in {"quick", "standard", "series"} else "standard"
    # The outline is generated in a separate request after the user confirms
    # the brief and scale. Never let an intake provider response skip that UX.
    outline: list[CourseOutlineItem] = []
    # Providers occasionally put the lead-in in assistantMessage and omit the
    # actual question. Keep the API contract deterministic so the client never
    # enables answer controls without a question to answer.
    fallback_question = "为了更准确地设计课程，请告诉我你希望学完后能够完成什么？"
    question = (result.question or "").strip()
    assistant_message = (result.assistant_message or question or fallback_question).strip()
    if not result.ready:
        question = question or fallback_question
    return CourseDesignTurnResponse(
        brief=normalized,
        assistant_message=assistant_message,
        question=None if result.ready else question,
        quick_options=[] if result.ready else result.quick_options[:4],
        ready=result.ready,
        recommended_scale=normalized_scale,
        course_scale=scale or normalized_scale,
        outline=outline,
        turn=turn,
    )


@router.post("/course-design/outline", response_model=CourseOutlineResponse)
async def course_design_outline(payload: CourseOutlineRequest, db=Depends(get_db)):
    gateway = restore_active_provider(db, current_user_id())
    try:
        draft = await CourseOutlineAgent(gateway).generate(
            payload.brief.model_dump(by_alias=True), payload.course_scale
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"AI 未能生成有效课程大纲：{exc}") from exc
    return CourseOutlineResponse(course_scale=payload.course_scale, outline=draft)


@router.post("/course-design/outline/revise", response_model=CourseOutlineRevisionResponse)
async def revise_course_design_outline(payload: CourseOutlineRevisionRequest, db=Depends(get_db)):
    gateway = restore_active_provider(db, current_user_id())
    try:
        outline, assistant_message = await CourseOutlineAgent(gateway).revise(
            payload.brief.model_dump(by_alias=True), payload.course_scale,
            [item.model_dump(by_alias=True) for item in payload.current_outline],
            payload.feedback,
            [message.model_dump() for message in payload.messages],
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"AI 未能生成有效课程大纲：{exc}") from exc
    return CourseOutlineRevisionResponse(
        course_scale=payload.course_scale, outline=outline, assistant_message=assistant_message
    )
