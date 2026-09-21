"""Generate the reviewable outline after intake is complete."""

import json

from ..ai.gateway import AIGateway
from .language_policy import infer_response_language, response_language_instruction
from .prompts import COURSE_OUTLINE_SYSTEM
from .schemas import CourseOutlineDraft, CourseOutlineRevisionDraft


_SCALE_COUNTS = {"quick": 3, "standard": 6, "series": 10}


class CourseOutlineAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    @staticmethod
    def _validate_outline(outline, expected_count: int, *, include_titles: bool = False) -> None:
        if len(outline) != expected_count:
            raise ValueError(f"模型返回 {len(outline)} 节，期望 {expected_count} 节")
        titles = [item.title.strip() for item in outline]
        objectives = [item.objective.strip() for item in outline]
        if not all(titles) or len(set(titles)) != len(titles):
            raise ValueError("大纲标题必须非空且互不重复")
        if not all(objectives) or len(set(objectives)) != len(objectives):
            raise ValueError("大纲目标必须非空且互不重复")
        values = (*titles, *objectives) if include_titles else objectives
        if any("建立并应用一个关键能力" in value for value in values):
            raise ValueError("大纲包含无效占位内容")

    async def _repair(
        self,
        *,
        task: str,
        schema: dict,
        language: str,
        brief: dict,
        scale: str,
        expected_count: int,
        original: dict,
        validation_error: ValueError,
        revision_context: dict | None = None,
    ) -> dict:
        """Ask the provider once to repair an invalid structured outline response."""
        return await self.gateway.structured(
            [
                {
                    "role": "system",
                    "content": (
                        COURSE_OUTLINE_SYSTEM + "\n" + response_language_instruction(language)
                        + "\n这是一次结构化修复请求。必须只返回完整、有效的大纲 JSON；"
                        f"必须恰好返回 {expected_count} 节，标题和目标均非空且互不重复。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "task": "repair_outline",
                        "courseScale": scale,
                        "expectedCount": expected_count,
                        "brief": brief,
                        "originalResponse": original,
                        "validationError": str(validation_error),
                        "revisionContext": revision_context,
                        "responseLanguage": language,
                    }, ensure_ascii=False),
                },
            ],
            task=task,
            schema=schema,
        )

    async def generate(self, brief: dict, scale: str) -> list[dict[str, str]]:
        expected_count = _SCALE_COUNTS[scale]
        language = infer_response_language(brief.get("topic", ""))
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_OUTLINE_SYSTEM + "\n" + response_language_instruction(language)},
                {
                    "role": "user",
                    "content": f"responseLanguage={language}\n课程规模：{scale}（必须生成 {expected_count} 节）\n结构化需求：{json.dumps(brief, ensure_ascii=False)}",
                },
            ],
            task="course_outline",
            schema=CourseOutlineDraft.model_json_schema(),
        )
        try:
            draft = CourseOutlineDraft.model_validate(result)
            self._validate_outline(draft.outline, expected_count)
        except Exception as exc:
            failure = ValueError("模型返回的大纲格式无效") if not isinstance(exc, ValueError) else exc
            repaired = await self._repair(
                task="course_outline", schema=CourseOutlineDraft.model_json_schema(), language=language,
                brief=brief, scale=scale, expected_count=expected_count, original=result,
                validation_error=failure,
            )
            try:
                draft = CourseOutlineDraft.model_validate(repaired)
                self._validate_outline(draft.outline, expected_count)
            except Exception as repair_exc:
                detail = "模型返回的大纲格式无效" if not isinstance(repair_exc, ValueError) else str(repair_exc)
                raise ValueError(f"模型修复后仍未生成有效大纲：{detail}") from repair_exc
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
        language = infer_response_language(brief.get("topic", ""))
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_OUTLINE_SYSTEM + "\n" + response_language_instruction(language) + "\n你正在修订已有大纲。保留合理结构，只按用户意见调整；必须返回 outline 和 assistant_message。"},
                {
                    "role": "user",
                    "content": (
                        f"课程规模：{scale}（必须生成 {expected_count} 节）\n"
                        f"responseLanguage={language}\n"
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
            self._validate_outline(draft.outline, expected_count, include_titles=True)
        except Exception as exc:
            failure = ValueError("模型返回的大纲修订格式无效") if not isinstance(exc, ValueError) else exc
            repaired = await self._repair(
                task="course_outline_revision", schema=CourseOutlineRevisionDraft.model_json_schema(), language=language,
                brief=brief, scale=scale, expected_count=expected_count, original=result,
                validation_error=failure,
                revision_context={"currentOutline": current_outline, "feedback": feedback, "messages": messages},
            )
            try:
                draft = CourseOutlineRevisionDraft.model_validate(repaired)
                self._validate_outline(draft.outline, expected_count, include_titles=True)
            except Exception as repair_exc:
                detail = "模型返回的大纲修订格式无效" if not isinstance(repair_exc, ValueError) else str(repair_exc)
                raise ValueError(f"模型修复后仍未生成有效大纲：{detail}") from repair_exc
        return [item.model_dump() for item in draft.outline], draft.assistant_message.strip()
