"""Pre-generation course requirements interview."""

import hashlib
import json
import re

from ..ai.gateway import AIGateway
from .language_policy import infer_response_language, response_language_instruction
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
    "collecting_prior_knowledge": "collecting_background",
    "context": "collecting_background",
    "prior_context": "collecting_background",
    "collecting_context": "collecting_background",
    "collecting_background": "collecting_background",
    "brief": "reviewing_brief",
    "reviewing_brief": "reviewing_brief",
}

_QUESTION_TARGET_ALIASES = {
    "learninggoals": "learningGoals",
    "learning_goals": "learningGoals",
    "learning-goals": "learningGoals",
    "goals": "learningGoals",
    "learninggoaldetails": "learningGoals",
    "learningoutcome": "learningGoals",
    "learninggoal": "learningGoals",
    "priorknowledgelevels": "priorKnowledgeLevels",
    "prior_knowledge_levels": "priorKnowledgeLevels",
    "prior-knowledge-levels": "priorKnowledgeLevels",
    "prior_knowledge": "priorKnowledgeLevels",
    "prior-knowledge": "priorKnowledgeLevels",
    "background": "priorKnowledgeLevels",
    "priorknowledgedetails": "priorKnowledgeLevels",
    "priorknowledge": "priorKnowledgeLevels",
    "priorknowledgelevel": "priorKnowledgeLevels",
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


def _question_target(value: object, question_stage: str) -> str:
    # The normalized question stage is authoritative. Older models sometimes
    # reuse the previous target when advancing; accepting that value would
    # make a valid stage transition fail the service's canonical guard.
    canonical = "learningGoals" if question_stage == "collecting_goals" else "priorKnowledgeLevels"
    if value is None or not str(value).strip():
        return canonical
    raw = str(value).strip()
    alias = _QUESTION_TARGET_ALIASES.get(raw.lower())
    if alias is None:
        raise CourseIntakeInvalidResult(f"问题 target 无法识别：{value}")
    return canonical


def _next_stage(stage: str) -> str:
    return "collecting_background" if stage == "collecting_goals" else "reviewing_brief"


def _raw_legacy_question(result: dict) -> object:
    raw_question = result.get("nextQuestion")
    if raw_question is None and isinstance(result.get("question"), dict):
        return result["question"]
    if raw_question is None and isinstance(result.get("question"), str):
        return {"title": result["question"]}
    return raw_question


def _normalize_question(raw_question: object, *, stage: str, field_name: str) -> dict | None:
    if raw_question is None:
        return None
    if not isinstance(raw_question, dict):
        raise CourseIntakeInvalidResult(f"{field_name} 不是对象")
    question = dict(raw_question)
    if question.get("stage"):
        _stage(question.get("stage"), stage)
    target = _question_target(question.get("target"), stage)
    title = question.get("title") or question.get("question") or question.get("prompt") or question.get("text")
    if not isinstance(title, str) or not title.strip():
        raise CourseIntakeInvalidResult(f"{field_name} 缺少 title")
    options = question.get("options", question.get("quickOptions", []))
    if not isinstance(options, list):
        raise CourseIntakeInvalidResult(f"{field_name}.options 不是数组")
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
    fingerprint = "\n".join([stage, title.strip(), *(item["label"] for item in normalized_options)])
    question["id"] = question.get("id") or f"{stage}-{hashlib.sha256(fingerprint.encode()).hexdigest()[:12]}"
    question["stage"] = stage
    question["target"] = target
    question["type"] = "multi_select_with_text"
    question["title"] = title.strip()
    question["description"] = question.get("description") or ""
    question["options"] = normalized_options
    question["allowCustom"] = question.get("allowCustom", question.get("allowCustomText", True))
    question["minimumSelections"] = question.get("minimumSelections", 0)
    return question


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

    server_next_stage = _next_stage(current_stage)
    sufficiency = result.get("sufficiency")
    if sufficiency in {"sufficient", "needs_clarification"}:
        # Once the new protocol is present, deprecated transition advice is
        # ignored completely, including malformed nextStage values.
        next_stage = server_next_stage if sufficiency == "sufficient" else current_stage
        decision = {
            "type": "advance" if sufficiency == "sufficient" else "ask_follow_up",
            "nextStage": next_stage,
        }
    else:
        ready = result.get("ready")
        legacy_stage = _stage(result.get("stage"), current_stage)
        next_stage = _stage(
            result.get("decision", {}).get("nextStage")
            if isinstance(result.get("decision"), dict)
            else legacy_stage,
            current_stage,
        )
        decision = result.get("decision")
        if not isinstance(decision, dict):
            if ready is True:
                next_stage = server_next_stage
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
        if decision.get("type") == "ask_follow_up":
            decision["nextStage"] = current_stage
        sufficiency = (
            "sufficient"
            if decision.get("type") == "advance" and next_stage != current_stage
            else "needs_clarification"
        )
    result["decision"] = decision
    result["sufficiency"] = sufficiency

    legacy_question = _raw_legacy_question(result)
    clarification_raw = result.get("clarificationQuestion")
    next_stage_raw = result.get("nextStageQuestion")
    if sufficiency == "needs_clarification" and clarification_raw is None:
        clarification_raw = legacy_question
    if sufficiency == "sufficient" and next_stage_raw is None:
        next_stage_raw = legacy_question
    clarification = None
    next_stage_question = None
    if sufficiency == "needs_clarification":
        clarification = _normalize_question(
            clarification_raw, stage=current_stage, field_name="clarificationQuestion"
        )
    elif server_next_stage != "reviewing_brief":
        next_stage_question = _normalize_question(
            next_stage_raw, stage=server_next_stage, field_name="nextStageQuestion"
        )
    result["clarificationQuestion"] = clarification
    result["nextStageQuestion"] = next_stage_question
    # Keep the compatibility projection for callers outside the state service
    # during the dual-read observation window.
    result["nextQuestion"] = clarification if sufficiency == "needs_clarification" else next_stage_question
    result["recommendedScale"] = result.get("recommendedScale", result.get("recommended_scale"))
    result["assistantMessage"] = result.get("assistantMessage", result.get("assistant_message", ""))
    try:
        return CourseIntakeStateResult.model_validate(result)
    except Exception as exc:
        raise CourseIntakeInvalidResult("课程需求 Agent 返回结构无效") from exc


class CourseIntakeAgent:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    @staticmethod
    def _missing_transition_summary(
        result: CourseIntakeStateResult, stage: str, *, require_summary: bool = False
    ) -> str | None:
        if not require_summary and result.sufficiency != "sufficient":
            return None
        if stage == "collecting_goals":
            if not str(result.brief_patch.get("learningOutcome", "") or "").strip():
                return "learningOutcome"
        if stage == "collecting_background":
            if not str(result.brief_patch.get("priorKnowledge", "") or "").strip():
                return "priorKnowledge"
        return None

    async def _repair_transition_result(
        self,
        *,
        stage: str,
        brief: dict,
        answer: dict,
        original: dict,
        missing_field: str,
        language: str,
    ) -> CourseIntakeStateResult:
        """Ask the same structured intake contract to repair one unsafe transition."""
        result = await self.gateway.structured(
            [
                {
                    "role": "system",
                    "content": (
                        COURSE_INTAKE_STATE_SYSTEM
                        + "\n"
                        + response_language_instruction(language)
                        + f"\n这是一次协议修复请求。当前阶段必须保持为 {stage}，只允许进入下一个合法阶段；必须补齐非空 {missing_field}。"
                        "请基于原始 brief、用户回答和原响应补齐字段，只返回完整的课程需求状态协议，不得自行跳跃阶段。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "repair_intake_state",
                            "stage": stage,
                            "brief": brief,
                            "answer": answer,
                            "originalResponse": original,
                            "missingField": missing_field,
                            "responseLanguage": language,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            task="course_intake_state",
            schema=CourseIntakeStateResult.model_json_schema(),
        )
        return normalize_state_result(result, stage=stage)

    async def _normalize_with_transition_repair(
        self,
        *,
        result: dict,
        stage: str,
        brief: dict,
        answer: dict,
        language: str,
        require_summary: bool = False,
        strict_summary: bool = False,
    ) -> CourseIntakeStateResult:
        parsed = normalize_state_result(result, stage=stage)
        missing = self._missing_transition_summary(parsed, stage, require_summary=require_summary)
        if not missing and parsed.sufficiency == "needs_clarification" and not parsed.clarification_question:
            missing = "clarificationQuestion"
        if not missing:
            return parsed
        try:
            repaired = await self._repair_transition_result(
                stage=stage,
                brief=brief,
                answer=answer,
                original=result,
                missing_field=missing,
                language=language,
            )
        except (ValueError, TypeError, KeyError):
            if strict_summary:
                raise
            return parsed
        if missing == "clarificationQuestion" and (
            repaired.sufficiency != "needs_clarification" or not repaired.clarification_question
        ):
            return parsed
        if (strict_summary
                and self._missing_transition_summary(repaired, stage, require_summary=require_summary)):
            raise CourseIntakeInvalidResult(f"课程需求 Agent 修复后仍缺少 {missing}")
        return repaired

    async def turn(self, messages: list[dict], brief: dict | None = None, scale: str | None = None) -> CourseIntakeResult:
        current = dict(brief or {})
        history = json.dumps(messages, ensure_ascii=False)
        language = infer_response_language(current.get("topic") or next(
            (item.get("content", "") for item in messages if item.get("role") == "user"),
            "",
        ))
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_INTAKE_SYSTEM + "\n" + response_language_instruction(language)},
                {"role": "user", "content": f"responseLanguage={language}\n已有 brief：{json.dumps(current, ensure_ascii=False)}\n对话：{history}\n用户选择的规模：{scale or '未选择'}"},
            ],
            task="course_intake",
            schema=CourseIntakeResult.model_json_schema(),
        )
        parsed = CourseIntakeResult.model_validate(result)
        merged = dict(current)
        for key, value in parsed.brief.items():
            if value not in (None, "", [], {}):
                merged[key] = value
        # The caller owns the original topic. Providers may translate or
        # otherwise restate it while filling the brief, but must not replace it.
        if current.get("topic"):
            merged["topic"] = current["topic"]
        parsed.brief = merged
        return parsed

    async def answer(
        self,
        *,
        stage: str,
        brief: dict,
        selected_labels: list[str],
        custom_text: str = "",
        answered_question: dict | None = None,
    ) -> CourseIntakeStateResult:
        """Evaluate one explicit stage answer; the service owns transitions."""
        language = infer_response_language(brief.get("topic", ""))
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_INTAKE_STATE_SYSTEM + "\n" + response_language_instruction(language)},
                {"role": "user", "content": json.dumps({
                    "task": "evaluate_intake_answer",
                    "stage": stage,
                    "brief": brief,
                    "answer": {"selectedLabels": selected_labels, "customText": custom_text},
                    "answeredQuestion": answered_question or {},
                    "responseLanguage": language,
                }, ensure_ascii=False)},
            ],
            task="course_intake_state",
            schema=CourseIntakeStateResult.model_json_schema(),
        )
        return await self._normalize_with_transition_repair(
            result=result,
            stage=stage,
            brief=brief,
            answer={"selectedLabels": selected_labels, "customText": custom_text},
            language=language,
        )

    async def start(self, *, topic: str) -> CourseIntakeStateResult:
        language = infer_response_language(topic)
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_INTAKE_STATE_SYSTEM + "\n" + response_language_instruction(language)},
                {"role": "user", "content": json.dumps({"task": "start_intake", "topic": topic, "responseLanguage": language}, ensure_ascii=False)},
            ],
            task="course_intake_state",
            schema=CourseIntakeStateResult.model_json_schema(),
        )
        return normalize_state_result(result, stage="collecting_goals")

    async def complete(self, *, stage: str, brief: dict) -> CourseIntakeStateResult:
        language = infer_response_language(brief.get("topic", ""))
        result = await self.gateway.structured(
            [
                {"role": "system", "content": COURSE_INTAKE_STATE_SYSTEM + "\n" + response_language_instruction(language)},
                {"role": "user", "content": json.dumps({
                    "task": "complete_with_ai", "stage": stage, "brief": brief,
                    "responseLanguage": language,
                }, ensure_ascii=False)},
            ],
            task="course_intake_state",
            schema=CourseIntakeStateResult.model_json_schema(),
        )
        return await self._normalize_with_transition_repair(
            result=result,
            stage=stage,
            brief=brief,
            answer={},
            language=language,
            require_summary=True,
            strict_summary=True,
        )
