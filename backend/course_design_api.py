"""Course-design intake routes."""

from fastapi import APIRouter, Depends

from .agents.course_intake_agent import CourseIntakeAgent
from .agents.schemas import CourseIntakeResult
from .db import get_db
from .schemas import CourseBrief, CourseDesignTurnRequest, CourseDesignTurnResponse, CourseOutlineItem
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
    # An outline is a confirmation artifact.  During intake keep asking the
    # next high-value question instead of manufacturing one here (the client
    # uses its presence to enter the review stage).
    if result.ready and not result.outline:
        count = {"quick": 3, "standard": 6, "series": 10}.get(scale or result.recommended_scale, 6)
        topic = brief.topic or brief.learning_outcome or "课程主题"
        result.outline = [{"title": f"{topic}：第 {index + 1} 个学习单元", "objective": "建立并应用一个关键能力"} for index in range(count)]
    normalized = CourseBrief.model_validate(result.brief)
    normalized_scale = result.recommended_scale if result.recommended_scale in {"quick", "standard", "series"} else "standard"
    outline = [CourseOutlineItem.model_validate(item) for item in result.outline[:12]]
    return CourseDesignTurnResponse(
        brief=normalized,
        assistant_message=result.assistant_message or result.question or "请补充你的学习目标。",
        question=None if result.ready else result.question,
        quick_options=[] if result.ready else result.quick_options[:4],
        ready=result.ready,
        recommended_scale=normalized_scale,
        course_scale=scale or normalized_scale,
        outline=outline,
        turn=turn,
    )
