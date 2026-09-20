"""Pre-generation course requirements interview."""

import json

from ..ai.gateway import AIGateway
from .prompts import COURSE_INTAKE_STATE_SYSTEM, COURSE_INTAKE_SYSTEM
from .schemas import CourseIntakeResult, CourseIntakeStateResult


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

    async def answer(
        self,
        *,
        stage: str,
        brief: dict,
        selected_labels: list[str],
        custom_text: str = "",
    ) -> CourseIntakeStateResult:
        """Evaluate one explicit stage answer; the service owns transitions."""
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_INTAKE_STATE_SYSTEM},
                {"role": "user", "content": json.dumps({
                    "task": "evaluate_intake_answer",
                    "stage": stage,
                    "brief": brief,
                    "answer": {"selectedLabels": selected_labels, "customText": custom_text},
                }, ensure_ascii=False)},
            ],
            task="course_intake_state",
            schema=CourseIntakeStateResult.model_json_schema(),
        )
        return CourseIntakeStateResult.model_validate(result)

    async def start(self, *, topic: str) -> CourseIntakeStateResult:
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_INTAKE_STATE_SYSTEM},
                {"role": "user", "content": json.dumps({"task": "start_intake", "topic": topic}, ensure_ascii=False)},
            ],
            task="course_intake_state",
            schema=CourseIntakeStateResult.model_json_schema(),
        )
        return CourseIntakeStateResult.model_validate(result)

    async def complete(self, *, stage: str, brief: dict) -> CourseIntakeStateResult:
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_INTAKE_STATE_SYSTEM},
                {"role": "user", "content": json.dumps({
                    "task": "complete_with_ai", "stage": stage, "brief": brief,
                }, ensure_ascii=False)},
            ],
            task="course_intake_state",
            schema=CourseIntakeStateResult.model_json_schema(),
        )
        return CourseIntakeStateResult.model_validate(result)
