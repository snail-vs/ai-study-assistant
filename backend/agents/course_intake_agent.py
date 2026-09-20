"""Pre-generation course requirements interview."""

import json
import re

from ..ai.gateway import AIGateway
from .prompts import COURSE_INTAKE_STATE_SYSTEM, COURSE_INTAKE_SYSTEM
from .schemas import CourseIntakeResult, CourseIntakeStateResult


class CourseIntakeInvalidResult(ValueError):
    """Provider returned an intake shape that cannot be safely normalized."""


_STAGE_ALIASES = {
    "goals": "collecting_goals",
    "learning_goals": "collecting_goals",
    "collecting_goals": "collecting_goals",
    "background": "collecting_background",
    "prior_knowledge": "collecting_background",
    "collecting_background": "collecting_background",
    "brief": "reviewing_brief",
    "reviewing_brief": "reviewing_brief",
}


def _stage(value: object, fallback: str) -> str:
    fallback_key = str(fallback or "").strip().lower()
    if fallback_key and fallback_key not in _STAGE_ALIASES:
        raise CourseIntakeInvalidResult(f"未知课程设计阶段：{fallback}")
    value_key = str(value or "").strip().lower()
    if not value_key:
        return _STAGE_ALIASES.get(fallback_key, fallback_key)
    if value_key not in _STAGE_ALIASES:
        raise CourseIntakeInvalidResult(f"未知课程设计阶段：{value}")
    return _STAGE_ALIASES[value_key]


def _option_id(value: str, index: int) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value).strip("-").lower()
    return slug[:80] or f"option-{index + 1}"


def normalize_state_result(raw: dict, *, stage: str) -> CourseIntakeStateResult:
    """Normalize known legacy intake shapes, then apply the strict schema."""
    if not isinstance(raw, dict):
        raise CourseIntakeInvalidResult("课程需求 Agent 返回值不是对象")
    current_stage = _stage(stage, stage)
    result = dict(raw)
    patch = result.get("briefPatch")
    if patch is None:
        patch = result.get("brief", {})
    if not isinstance(patch, dict):
        raise CourseIntakeInvalidResult("brief 不是对象")
    result["briefPatch"] = patch

    ready = result.get("ready")
    legacy_stage = _stage(result.get("stage"), current_stage)
    next_stage = _stage(result.get("decision", {}).get("nextStage") if isinstance(result.get("decision"), dict) else legacy_stage, current_stage)
    decision = result.get("decision")
    if not isinstance(decision, dict):
        if ready is True:
            next_stage = "collecting_background" if current_stage == "collecting_goals" else "reviewing_brief"
            decision = {"type": "advance", "nextStage": next_stage}
        elif legacy_stage != current_stage:
            decision = {"type": "advance", "nextStage": legacy_stage}
        else:
            decision = {"type": "ask_follow_up", "nextStage": current_stage}
    else:
        decision = dict(decision)
        decision["nextStage"] = _stage(decision.get("nextStage"), next_stage)
        if "type" not in decision:
            decision["type"] = "advance" if decision["nextStage"] != current_stage else "ask_follow_up"
    result["decision"] = decision

    raw_question = result.get("nextQuestion")
    if raw_question is None and isinstance(result.get("question"), dict):
        raw_question = result["question"]
    elif raw_question is None and isinstance(result.get("question"), str):
        raw_question = {"title": result["question"]}
    target_stage = _stage(decision.get("nextStage"), current_stage)
    if raw_question is not None:
        if not isinstance(raw_question, dict):
            raise CourseIntakeInvalidResult("nextQuestion 不是对象")
        question = dict(raw_question)
        question_stage = _stage(question.get("stage"), target_stage)
        target = question.get("target")
        if not target:
            target = "learningGoals" if question_stage == "collecting_goals" else "priorKnowledgeLevels"
        title = question.get("title") or question.get("question") or question.get("prompt") or question.get("text")
        if not isinstance(title, str) or not title.strip():
            raise CourseIntakeInvalidResult("nextQuestion 缺少 title")
        options = question.get("options", question.get("quickOptions", []))
        if not isinstance(options, list):
            raise CourseIntakeInvalidResult("nextQuestion.options 不是数组")
        normalized_options = []
        for index, option in enumerate(options):
            if isinstance(option, str):
                label = option.strip()
                option_id = _option_id(label, index)
            elif isinstance(option, dict):
                label = option.get("label") or option.get("text") or option.get("value")
                option_id = option.get("id") or option.get("value")
                if not isinstance(label, str) or not label.strip():
                    raise CourseIntakeInvalidResult("问题选项缺少 label/value")
                option_id = str(option_id or _option_id(label, index))
            else:
                raise CourseIntakeInvalidResult("问题选项格式无效")
            normalized_options.append({"id": option_id, "label": label.strip()})
        question["id"] = question.get("id") or f"{question_stage}-question"
        question["stage"] = question_stage
        question["target"] = target
        question["type"] = "multi_select_with_text"
        question["title"] = title.strip()
        question["description"] = question.get("description") or ""
        question["options"] = normalized_options
        question["allowCustom"] = question.get("allowCustom", question.get("allowCustomText", True))
        question["minimumSelections"] = question.get("minimumSelections", 0)
        result["nextQuestion"] = question
    else:
        result["nextQuestion"] = None
    result["recommendedScale"] = result.get("recommendedScale", result.get("recommended_scale"))
    result["assistantMessage"] = result.get("assistantMessage", result.get("assistant_message", ""))
    try:
        return CourseIntakeStateResult.model_validate(result)
    except Exception as exc:
        raise CourseIntakeInvalidResult("课程需求 Agent 返回结构无效") from exc


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
        return normalize_state_result(result, stage=stage)

    async def start(self, *, topic: str) -> CourseIntakeStateResult:
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_INTAKE_STATE_SYSTEM},
                {"role": "user", "content": json.dumps({"task": "start_intake", "topic": topic}, ensure_ascii=False)},
            ],
            task="course_intake_state",
            schema=CourseIntakeStateResult.model_json_schema(),
        )
        return normalize_state_result(result, stage="collecting_goals")

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
        return normalize_state_result(result, stage=stage)
