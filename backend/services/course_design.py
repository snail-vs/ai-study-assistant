"""Server-owned orchestration for the guided course design workflow."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from ..agents.course_intake_agent import CourseIntakeAgent
from ..agents.outline_agent import CourseOutlineAgent
from ..models import CourseDesignSession, LearningSpace, new_id, now
from ..schemas import (
    CourseBrief,
    CourseDesignCommandRequest,
    CourseDesignQuestion,
    CourseDesignSessionResponse,
    CourseOutlineItem,
)
from .course_generation import schedule_course_generation
from .provider_settings import restore_active_provider


class CourseDesignConflict(Exception):
    pass


class CourseDesignInvalid(Exception):
    pass


ALLOWED_ACTIONS = {
    "collecting_goals": ["answer_question", "complete_with_ai", "restart"],
    "collecting_background": ["answer_question", "complete_with_ai", "go_back", "restart"],
    "reviewing_brief": ["update_brief", "select_scale", "generate_outline", "go_back", "restart"],
    "reviewing_outline": ["revise_outline", "generate_outline", "confirm_outline", "go_back", "restart"],
    "outline_confirmed": ["generate_course", "revise_outline", "go_back", "restart"],
    "course_queued": [],
    "cancelled": ["restart"],
}

GOAL_FIELDS = {"learningGoals", "learningGoalDetails", "learningOutcome"}
BACKGROUND_FIELDS = {"priorKnowledgeLevels", "priorKnowledgeDetails", "priorKnowledge"}
INTAKE_FIELDS = GOAL_FIELDS | BACKGROUND_FIELDS
SCALE_VALUES = {"quick", "standard", "series"}
_SCALE_QUESTION_MARKERS = (
    "课程规模", "学习规模", "规模和节奏", "学习节奏", "学习时长", "时间与深度",
    "快速了解", "系统入门", "项目掌握", "2-3 节", "5-8 节", "8-12 节",
    "course scale", "learning pace", "duration", "quick overview", "standard course",
)
_CONFLICT_RESOLUTION_MARKERS = (
    "矛盾", "冲突", "既勾", "请选一个", "选择一个", "最贴近", "只能选",
    "conflict", "choose one", "closest match", "only choose",
)


def _initial_brief(topic: str, patch: dict) -> dict:
    """Build an intake brief without granting the provider ownership of topic."""
    return {"topic": topic, **{key: value for key, value in patch.items() if key in GOAL_FIELDS}}


def _question(data: dict | None) -> CourseDesignQuestion | None:
    if not data:
        return None
    return CourseDesignQuestion.model_validate(data)


def _is_scale_question(question: CourseDesignQuestion) -> bool:
    text = " ".join([
        question.title, question.description, *(option.label for option in question.options)
    ]).lower()
    return any(marker in text for marker in _SCALE_QUESTION_MARKERS)


def _is_conflict_resolution_question(question: dict) -> bool:
    text = " ".join(str(question.get(key, "")) for key in ("title", "description"))
    return any(marker in text for marker in _CONFLICT_RESOLUTION_MARKERS)


def _is_repeated_question(previous: dict, candidate: CourseDesignQuestion | None) -> bool:
    """Detect a provider restating the question that the learner just answered."""
    if not candidate:
        return False
    normalize = lambda value: re.sub(r"[\W_]+", "", str(value).casefold())
    return bool(normalize(previous.get("title")) and normalize(previous.get("title")) == normalize(candidate.title))


def _fallback_question(stage: str, topic: str) -> CourseDesignQuestion:
    if stage == "collecting_goals":
        return CourseDesignQuestion(
            id="collecting-goals-fallback", stage=stage, target="learningGoals",
            title=f"学习 {topic} 后，你最希望获得哪些能力？",
            options=[
                {"id": "understand-core", "label": "理解核心概念与工作原理"},
                {"id": "hands-on", "label": "能完成一个实际练习或小项目"},
                {"id": "apply-at-work", "label": "能在工作或真实场景中应用"},
            ],
        )
    return CourseDesignQuestion(
        id="collecting-background-fallback", stage=stage, target="priorKnowledgeLevels",
        title=f"在学习 {topic} 前，你目前有哪些相关基础？",
        options=[
            {"id": "no-programming", "label": "还没有相关编程或技术基础"},
            {"id": "other-language", "label": "会其他编程语言，但没系统学习过这个主题"},
            {"id": "basic-experience", "label": "了解基础概念，做过一些简单练习"},
            {"id": "practical-experience", "label": "有实际使用经验，想系统提升"},
        ],
    )


class CourseDesignService:
    def __init__(self, db, user_id: str, gateway=None):
        self.db = db
        self.user_id = user_id
        self.gateway = gateway

    def _gateway(self):
        if self.gateway is None:
            self.gateway = restore_active_provider(self.db, self.user_id)
        return self.gateway

    @staticmethod
    def _safe_intake_question(question: CourseDesignQuestion, stage: str, topic: str) -> CourseDesignQuestion:
        """Keep scale selection out of the goals/background interview steps."""
        if _is_scale_question(question):
            return _fallback_question(stage, topic)
        return question

    def _owned(self, session_id: str) -> CourseDesignSession:
        session = self.db.scalar(select(CourseDesignSession).where(
            CourseDesignSession.id == session_id,
            CourseDesignSession.user_id == self.user_id,
        ))
        if not session:
            raise CourseDesignInvalid("课程设计会话不存在")
        return session

    def _repair_unsafe_current_question(self, session: CourseDesignSession) -> None:
        """Repair persisted questions created before semantic validation existed."""
        if session.state not in {"collecting_goals", "collecting_background"}:
            return
        question = _question(session.current_question)
        if not question or not _is_scale_question(question):
            return
        repaired = _fallback_question(session.state, session.topic)
        session.current_question = repaired.model_dump(by_alias=True)
        questions = session.questions
        questions[session.state] = session.current_question
        session.questions = questions
        self.db.commit()
        self.db.refresh(session)

    def _snapshot(self, session: CourseDesignSession) -> CourseDesignSessionResponse:
        return CourseDesignSessionResponse(
            sessionId=session.id,
            learningSpaceId=session.source_learning_space_id,
            state=session.state,
            revision=session.revision,
            briefRevision=session.brief_revision,
            brief=CourseBrief.model_validate(session.brief),
            currentQuestion=_question(session.current_question),
            recommendedScale=session.recommended_scale,
            selectedScale=session.selected_scale,
            outline=[CourseOutlineItem.model_validate(item) for item in session.outline],
            outlineConfirmed=bool(session.outline_confirmed_at),
            allowedActions=ALLOWED_ACTIONS.get(session.state, []),
            operation=session.operation,
            outlineRevisionMessages=session.outline_revision_messages,
        )

    @staticmethod
    def _payload(command: CourseDesignCommandRequest) -> dict:
        return command.payload.model_dump(by_alias=True, exclude_none=True)

    def _commit(self, session: CourseDesignSession, command_id: str | None = None) -> CourseDesignSessionResponse:
        if command_id:
            processed = session.processed_commands
            if command_id not in processed:
                session.processed_commands = [*processed, command_id][-100:]
        session.revision += 1
        session.updated_at = now()
        try:
            self.db.commit()
        except StaleDataError as exc:
            self.db.rollback()
            raise CourseDesignConflict("课程设计会话已更新，请刷新后重试") from exc
        self.db.refresh(session)
        return self._snapshot(session)

    async def create(self, topic: str, source_learning_space_id: str | None = None) -> CourseDesignSessionResponse:
        if source_learning_space_id:
            source_space = self.db.scalar(select(LearningSpace).where(
                LearningSpace.id == source_learning_space_id,
                LearningSpace.user_id == self.user_id,
            ))
            if not source_space:
                raise CourseDesignInvalid("课程空间不存在或不属于当前用户")
            if source_space.generation_status != "failed":
                raise CourseDesignInvalid("只有生成失败的课程才能重试")
        agent = CourseIntakeAgent(self._gateway())
        try:
            result = await agent.start(topic=topic)
        except ValueError as exc:
            raise CourseDesignInvalid(f"AI 返回的课程需求格式无效：{exc}") from exc
        question = result.next_question
        if not question or question.stage != "collecting_goals" or question.target != "learningGoals":
            raise CourseDesignInvalid("Intake Agent 返回了无效的目标问题")
        question = self._safe_intake_question(question, "collecting_goals", topic)
        if set(result.brief_patch) - (GOAL_FIELDS | {"topic"}):
            raise CourseDesignInvalid("Intake Agent 返回了无效的目标字段")
        brief = _initial_brief(topic, result.brief_patch)
        session = CourseDesignSession(
            user_id=self.user_id, topic=topic, state="collecting_goals",
            source_learning_space_id=source_learning_space_id,
        )
        session.brief = CourseBrief.model_validate(brief).model_dump(by_alias=True)
        session.current_question = question.model_dump(by_alias=True)
        session.questions = {"collecting_goals": session.current_question}
        session.recommended_scale = result.recommended_scale
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return self._snapshot(session)

    def get(self, session_id: str) -> CourseDesignSessionResponse:
        session = self._owned(session_id)
        self._repair_unsafe_current_question(session)
        return self._snapshot(session)

    def _ensure_action(self, session: CourseDesignSession, command: CourseDesignCommandRequest) -> None:
        if command.type not in ALLOWED_ACTIONS.get(session.state, []):
            raise CourseDesignConflict(f"当前状态不允许执行 {command.type}")
        if command.expected_revision != session.revision:
            raise CourseDesignConflict("课程设计会话已更新，请刷新后重试")

    @staticmethod
    def _answer_payload(payload: dict) -> tuple[str, list[str], str]:
        answer = payload.get("answer", payload)
        if not isinstance(answer, dict):
            raise CourseDesignInvalid("答案格式无效")
        question_id = str(answer.get("questionId", ""))
        selected = answer.get("selectedOptionIds", [])
        custom = str(answer.get("customText", "") or "").strip()
        if not question_id or not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
            raise CourseDesignInvalid("答案格式无效")
        if not selected and not custom:
            raise CourseDesignInvalid("请至少选择一项或填写补充说明")
        return question_id, selected, custom

    async def _answer(self, session: CourseDesignSession, command: CourseDesignCommandRequest) -> CourseDesignSessionResponse:
        question_id, selected_ids, custom = self._answer_payload(self._payload(command))
        current_question = session.current_question
        if question_id != current_question.get("id"):
            raise CourseDesignConflict("问题已更新，请刷新后重新回答")
        option_map = {item["id"]: item["label"] for item in current_question.get("options", [])}
        if any(item not in option_map for item in selected_ids):
            raise CourseDesignInvalid("答案包含当前问题不存在的选项")
        labels = [option_map[item] for item in selected_ids]
        try:
            agent_result = await CourseIntakeAgent(self._gateway()).answer(
                stage=session.state, brief=session.brief, selected_labels=labels, custom_text=custom,
                answered_question=current_question,
            )
        except ValueError as exc:
            raise CourseDesignInvalid(f"AI 返回的课程需求格式无效：{exc}") from exc
        allowed = GOAL_FIELDS if session.state == "collecting_goals" else BACKGROUND_FIELDS
        unknown = set(agent_result.brief_patch) - (INTAKE_FIELDS | {"topic"})
        if unknown:
            raise CourseDesignInvalid("Agent 返回了当前阶段禁止修改的字段")
        patch = {key: value for key, value in agent_result.brief_patch.items() if key in allowed}
        replaces_previous = _is_conflict_resolution_question(current_question)
        if session.state == "collecting_goals":
            previous = session.brief.get("learningGoals", [])
            patch["learningGoals"] = labels if replaces_previous else list(dict.fromkeys([*previous, *labels]))
            if custom:
                prior = session.brief.get("learningGoalDetails", "")
                patch["learningGoalDetails"] = "；".join(dict.fromkeys(filter(None, [prior, custom])))
        else:
            previous = session.brief.get("priorKnowledgeLevels", [])
            patch["priorKnowledgeLevels"] = labels if replaces_previous else list(dict.fromkeys([*previous, *labels]))
            if custom:
                prior = session.brief.get("priorKnowledgeDetails", "")
                patch["priorKnowledgeDetails"] = "；".join(dict.fromkeys(filter(None, [prior, custom])))
        merged = {**session.brief, **patch}
        session.brief = CourseBrief.model_validate(merged).model_dump(by_alias=True)
        # A repeated follow-up leaves the learner in a loop.  The answer has
        # already been recorded above, so use the completion contract to
        # summarize this stage and advance instead of displaying it again.
        if (agent_result.decision.type == "ask_follow_up"
                and _is_repeated_question(current_question, agent_result.next_question)):
            try:
                agent_result = await CourseIntakeAgent(self._gateway()).complete(
                    stage=session.state, brief=session.brief
                )
            except ValueError as exc:
                raise CourseDesignInvalid(f"AI 返回的课程需求格式无效：{exc}") from exc
            unknown = set(agent_result.brief_patch) - (INTAKE_FIELDS | {"topic"})
            if unknown:
                raise CourseDesignInvalid("Agent 返回了当前阶段禁止修改的字段")
            patch = {key: value for key, value in agent_result.brief_patch.items() if key in allowed}
            selected_field = "learningGoals" if session.state == "collecting_goals" else "priorKnowledgeLevels"
            patch[selected_field] = list(dict.fromkeys([
                *session.brief.get(selected_field, []), *patch.get(selected_field, []),
            ]))
            session.brief = CourseBrief.model_validate({**session.brief, **patch}).model_dump(by_alias=True)
        next_stage = agent_result.decision.next_stage
        if agent_result.decision.type == "ask_follow_up":
            next_stage = session.state
        if session.state == "collecting_goals":
            if next_stage not in {"collecting_goals", "collecting_background"}:
                raise CourseDesignInvalid("Agent 不允许从目标阶段跳转到该状态")
        elif next_stage not in {"collecting_background", "reviewing_brief"}:
            raise CourseDesignInvalid("Agent 不允许从基础阶段跳转到该状态")
        if session.state == "collecting_goals" and next_stage == "collecting_background" and not session.brief.get("learningOutcome", "").strip():
            raise CourseDesignInvalid("Agent 必须返回学习目标总结")
        if session.state == "collecting_background" and next_stage == "reviewing_brief" and not session.brief.get("priorKnowledge", "").strip():
            raise CourseDesignInvalid("Agent 必须返回个人基础总结")
        if agent_result.recommended_scale in SCALE_VALUES:
            session.recommended_scale = agent_result.recommended_scale
        session.state = next_stage
        session.brief_revision += 1
        if next_stage == "reviewing_brief":
            session.current_question = {}
        else:
            next_question = agent_result.next_question
            expected_target = "learningGoals" if next_stage == "collecting_goals" else "priorKnowledgeLevels"
            if not next_question:
                if next_stage == current_question.get("stage"):
                    raise CourseDesignInvalid("Agent 必须返回当前阶段的追问")
                next_question = _fallback_question(next_stage, session.topic)
            if next_question.stage != next_stage or next_question.target != expected_target:
                raise CourseDesignInvalid("Agent 返回的问题目标字段与阶段不匹配")
            next_question = self._safe_intake_question(next_question, next_stage, session.topic)
            session.current_question = next_question.model_dump(by_alias=True)
            questions = session.questions
            questions[next_stage] = session.current_question
            session.questions = questions
        return self._commit(session, command.command_id)

    async def execute(self, session_id: str, command: CourseDesignCommandRequest) -> CourseDesignSessionResponse:
        session = self._owned(session_id)
        if command.command_id in session.processed_commands:
            return self._snapshot(session)
        self._ensure_action(session, command)
        if command.type == "answer_question":
            return await self._answer(session, command)
        if command.type == "complete_with_ai":
            try:
                result = await CourseIntakeAgent(self._gateway()).complete(stage=session.state, brief=session.brief)
            except ValueError as exc:
                raise CourseDesignInvalid(f"AI 返回的课程需求格式无效：{exc}") from exc
            allowed = GOAL_FIELDS if session.state == "collecting_goals" else BACKGROUND_FIELDS
            if set(result.brief_patch) - (INTAKE_FIELDS | {"topic"}):
                raise CourseDesignInvalid("Agent 返回了当前阶段禁止修改的字段")
            patch = {key: value for key, value in result.brief_patch.items() if key in allowed}
            session.brief = CourseBrief.model_validate({**session.brief, **patch}).model_dump(by_alias=True)
            if session.state == "collecting_goals":
                if result.decision.type != "advance" or result.decision.next_stage != "collecting_background":
                    raise CourseDesignInvalid("Agent 未完成目标阶段")
                if not session.brief.get("learningOutcome", "").strip() or not session.brief.get("learningGoals"):
                    raise CourseDesignInvalid("Agent 必须返回完整的学习目标总结")
                if not result.next_question or result.next_question.stage != "collecting_background" or result.next_question.target != "priorKnowledgeLevels":
                    raise CourseDesignInvalid("Agent 必须返回有效的基础问题")
                session.state = "collecting_background"
                question = self._safe_intake_question(result.next_question, "collecting_background", session.topic)
                session.current_question = question.model_dump(by_alias=True)
                questions = session.questions
                questions["collecting_background"] = session.current_question
                session.questions = questions
            else:
                if result.decision.type != "advance" or result.decision.next_stage != "reviewing_brief":
                    raise CourseDesignInvalid("Agent 未完成基础阶段")
                if not session.brief.get("priorKnowledge", "").strip() or not session.brief.get("priorKnowledgeLevels"):
                    raise CourseDesignInvalid("Agent 必须返回完整的个人基础总结")
                if result.next_question is not None:
                    raise CourseDesignInvalid("基础阶段完成后不应返回问题")
                session.state = "reviewing_brief"
                session.current_question = {}
            if result.recommended_scale in SCALE_VALUES:
                session.recommended_scale = result.recommended_scale
            session.brief_revision += 1
            return self._commit(session, command.command_id)
        if command.type == "update_brief":
            payload = self._payload(command).get("brief", {})
            allowed = {"learningOutcome", "priorKnowledge", "learningGoalDetails", "priorKnowledgeDetails", "useCase", "focus", "excludedTopics", "preferredStyle", "timeBudgetMinutes"}
            if any(key not in allowed for key in payload):
                raise CourseDesignInvalid("只能修改需求汇总字段")
            session.brief = CourseBrief.model_validate({**session.brief, **payload}).model_dump(by_alias=True)
            session.brief_revision += 1
            session.outline = []
            session.outline_basis_brief_revision = None
            session.outline_confirmed_at = None
            session.outline_revision_messages = []
            return self._commit(session, command.command_id)
        if command.type == "select_scale":
            scale = self._payload(command).get("courseScale")
            if scale not in SCALE_VALUES:
                raise CourseDesignInvalid("课程规模无效")
            if session.selected_scale != scale:
                session.selected_scale = scale
                session.brief_revision += 1
                session.outline = []
                session.outline_basis_brief_revision = None
                session.outline_confirmed_at = None
                session.outline_revision_messages = []
            return self._commit(session, command.command_id)
        if command.type in {"generate_outline", "revise_outline"}:
            return await self._outline(session, command)
        if command.type == "confirm_outline":
            if not session.outline or session.outline_basis_brief_revision != session.brief_revision:
                raise CourseDesignConflict("当前大纲已过期，请重新生成")
            session.outline_confirmed_at = datetime.utcnow()
            session.state = "outline_confirmed"
            return self._commit(session, command.command_id)
        if command.type == "generate_course":
            return self._generate_course(session, command)
        if command.type == "go_back":
            if session.state == "collecting_background":
                session.state = "collecting_goals"
                session.current_question = session.questions.get("collecting_goals", {})
                if not session.current_question:
                    raise CourseDesignInvalid("目标问题不存在，请重新开始课程设计")
            elif session.state == "reviewing_brief":
                session.state = "collecting_background"
                session.current_question = session.questions.get("collecting_background", {})
                if not session.current_question:
                    raise CourseDesignInvalid("基础问题不存在，请重新开始课程设计")
            elif session.state == "reviewing_outline":
                session.state = "reviewing_brief"
                session.outline = []
                session.outline_basis_brief_revision = None
                session.outline_confirmed_at = None
                session.outline_revision_messages = []
            elif session.state == "outline_confirmed":
                session.state = "reviewing_brief"
                session.outline = []
                session.outline_confirmed_at = None
                session.outline_basis_brief_revision = None
                session.outline_revision_messages = []
            return self._commit(session, command.command_id)
        if command.type == "restart":
            try:
                result = await CourseIntakeAgent(self._gateway()).start(topic=session.topic)
            except ValueError as exc:
                raise CourseDesignInvalid(f"AI 返回的课程需求格式无效：{exc}") from exc
            if (set(result.brief_patch) - (GOAL_FIELDS | {"topic"})
                    or not result.next_question
                    or result.next_question.stage != "collecting_goals"
                    or result.next_question.target != "learningGoals"):
                raise CourseDesignInvalid("Intake Agent 返回了无效的目标问题")
            session.state = "collecting_goals"
            session.brief = CourseBrief.model_validate(_initial_brief(session.topic, result.brief_patch)).model_dump(by_alias=True)
            question = self._safe_intake_question(result.next_question, "collecting_goals", session.topic)
            session.current_question = question.model_dump(by_alias=True)
            session.questions = {"collecting_goals": session.current_question}
            session.selected_scale = None
            session.outline = []
            session.outline_confirmed_at = None
            session.outline_basis_brief_revision = None
            session.outline_revision_messages = []
            session.brief_revision += 1
            return self._commit(session, command.command_id)
        raise CourseDesignInvalid("不支持的命令")

    async def _outline(self, session: CourseDesignSession, command: CourseDesignCommandRequest) -> CourseDesignSessionResponse:
        if not session.selected_scale:
            raise CourseDesignInvalid("请先选择课程规模")
        if not session.brief.get("learningOutcome", "").strip():
            raise CourseDesignInvalid("请先确认学习目标总结")
        if not session.brief.get("priorKnowledge", "").strip():
            raise CourseDesignInvalid("请先确认个人基础总结")
        if command.type == "revise_outline" and (not session.outline or session.outline_basis_brief_revision != session.brief_revision):
            raise CourseDesignConflict("当前大纲已过期，请重新生成")
        payload = self._payload(command)
        if command.type == "revise_outline" and not str(payload.get("feedback", "")).strip():
            raise CourseDesignInvalid("大纲修改建议不能为空")
        try:
            agent = CourseOutlineAgent(self._gateway())
            if command.type == "revise_outline":
                feedback = payload["feedback"].strip()
                outline, assistant_message = await agent.revise(
                    session.brief, session.selected_scale, session.outline,
                    feedback, session.outline_revision_messages,
                )
            else:
                outline = await agent.generate(session.brief, session.selected_scale)
        except (ValueError, KeyError) as exc:
            session.operation = {"status": "failed", "type": command.type, "error": str(exc)}
            self.db.commit()
            raise CourseDesignInvalid(f"AI 未能生成有效课程大纲：{exc}") from exc
        session.outline = [item.model_dump(by_alias=True) if hasattr(item, "model_dump") else dict(item) for item in outline]
        if command.type == "generate_outline":
            session.outline_revision_messages = []
        else:
            session.outline_revision_messages = [
                *session.outline_revision_messages,
                {"role": "user", "content": payload["feedback"].strip()},
                {"role": "assistant", "content": assistant_message},
            ][-20:]
        session.outline_basis_brief_revision = session.brief_revision
        session.outline_confirmed_at = None
        session.state = "reviewing_outline"
        session.operation = {"status": "succeeded", "type": command.type}
        return self._commit(session, command.command_id)

    def _generate_course(self, session: CourseDesignSession, command: CourseDesignCommandRequest) -> CourseDesignSessionResponse:
        if not session.outline_confirmed_at or not session.outline or session.outline_basis_brief_revision != session.brief_revision:
            raise CourseDesignConflict("只有确认有效大纲后才能生成课程")
        brief = CourseBrief.model_validate(session.brief)
        if session.source_learning_space_id:
            space = self.db.scalar(select(LearningSpace).where(
                LearningSpace.id == session.source_learning_space_id,
                LearningSpace.user_id == self.user_id,
            ))
            if not space or space.generation_status != "failed":
                raise CourseDesignConflict("课程空间已不可重试")
            space.title = session.topic
            space.learning_goal = brief.learning_outcome or session.topic
            space.course_brief = session.brief
            space.course_scale = session.selected_scale or "standard"
            space.course_outline = session.outline
            space.generation_status = "queued"
            space.generation_phase = "queued"
            space.generation_error = None
            space.generation_updated_at = now()
        else:
            space = LearningSpace(
                id=new_id(), user_id=self.user_id, title=session.topic,
                learning_goal=brief.learning_outcome or session.topic,
                course_brief_json=json.dumps(session.brief, ensure_ascii=False),
                course_scale=session.selected_scale or "standard",
                course_outline_json=json.dumps(session.outline, ensure_ascii=False),
                generation_status="queued", generation_phase="queued",
            )
            self.db.add(space)
        session.state = "course_queued"
        session.operation = {"status": "succeeded", "type": "generate_course", "spaceId": space.id}
        snapshot = self._commit(session, command.command_id)
        schedule_course_generation(space.id, self.user_id, space.learning_goal, session.brief, session.selected_scale, session.outline)
        return snapshot
