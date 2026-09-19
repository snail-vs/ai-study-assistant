"""Pre-generation course requirements interview."""

import json

from ..ai.gateway import AIGateway
from .prompts import COURSE_INTAKE_SYSTEM
from .schemas import CourseIntakeResult


class CourseIntakeAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    async def turn(self, messages: list[dict], brief: dict | None = None, scale: str | None = None) -> CourseIntakeResult:
        current = dict(brief or {})
        history = json.dumps(messages, ensure_ascii=False)
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_INTAKE_SYSTEM},
                {"role": "user", "content": f"已有 brief：{json.dumps(current, ensure_ascii=False)}\n对话：{history}\n用户选择的规模：{scale or '未选择'}"},
            ],
            task="course_intake",
            schema=CourseIntakeResult.model_json_schema(),
        )
        parsed = CourseIntakeResult.model_validate(result)
        merged = dict(current)
        for key, value in parsed.brief.items():
            if value not in (None, "", [], {}):
                merged[key] = value
        parsed.brief = merged
        return parsed
