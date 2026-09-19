"""Generate the reviewable outline after intake is complete."""

import json

from ..ai.gateway import AIGateway
from .prompts import COURSE_OUTLINE_SYSTEM
from .schemas import CourseOutlineDraft, CourseOutlineRevisionDraft


_SCALE_COUNTS = {"quick": 3, "standard": 6, "series": 10}


class CourseOutlineAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    async def generate(self, brief: dict, scale: str) -> list[dict[str, str]]:
        expected_count = _SCALE_COUNTS[scale]
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_OUTLINE_SYSTEM},
                {
                    "role": "user",
                    "content": f"课程规模：{scale}（必须生成 {expected_count} 节）\n结构化需求：{json.dumps(brief, ensure_ascii=False)}",
                },
            ],
            task="course_outline",
            schema=CourseOutlineDraft.model_json_schema(),
        )
        try:
            draft = CourseOutlineDraft.model_validate(result)
        except Exception as exc:
            raise ValueError("模型返回的大纲格式无效") from exc
        if len(draft.outline) != expected_count:
            raise ValueError(f"模型返回 {len(draft.outline)} 节，期望 {expected_count} 节")
        titles = [item.title.strip() for item in draft.outline]
        objectives = [item.objective.strip() for item in draft.outline]
        if not all(titles) or len(set(titles)) != len(titles):
            raise ValueError("大纲标题必须非空且互不重复")
        if not all(objectives) or len(set(objectives)) != len(objectives):
            raise ValueError("大纲目标必须非空且互不重复")
        if any("建立并应用一个关键能力" in objective for objective in objectives):
            raise ValueError("大纲包含无效占位目标")
        return [item.model_dump() for item in draft.outline]

    async def revise(
        self,
        brief: dict,
        scale: str,
        current_outline: list[dict],
        feedback: str,
        messages: list[dict],
    ) -> tuple[list[dict[str, str]], str]:
        expected_count = _SCALE_COUNTS[scale]
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_OUTLINE_SYSTEM + "\n你正在修订已有大纲。保留合理结构，只按用户意见调整；必须返回 outline 和 assistant_message。"},
                {
                    "role": "user",
                    "content": (
                        f"课程规模：{scale}（必须生成 {expected_count} 节）\n"
                        f"结构化需求：{json.dumps(brief, ensure_ascii=False)}\n"
                        f"当前大纲：{json.dumps(current_outline, ensure_ascii=False)}\n"
                        f"用户修改建议：{feedback}\n"
                        f"历史修订对话：{json.dumps(messages, ensure_ascii=False)}"
                    ),
                },
            ],
            task="course_outline_revision",
            schema=CourseOutlineRevisionDraft.model_json_schema(),
        )
        try:
            draft = CourseOutlineRevisionDraft.model_validate(result)
        except Exception as exc:
            raise ValueError("模型返回的大纲修订格式无效") from exc
        if len(draft.outline) != expected_count:
            raise ValueError(f"模型返回 {len(draft.outline)} 节，期望 {expected_count} 节")
        titles = [item.title.strip() for item in draft.outline]
        objectives = [item.objective.strip() for item in draft.outline]
        if not all(titles) or len(set(titles)) != len(titles):
            raise ValueError("大纲标题必须非空且互不重复")
        if not all(objectives) or len(set(objectives)) != len(objectives):
            raise ValueError("大纲目标必须非空且互不重复")
        if any("建立并应用一个关键能力" in value for value in (*titles, *objectives)):
            raise ValueError("大纲包含无效占位内容")
        return [item.model_dump() for item in draft.outline], draft.assistant_message.strip()
