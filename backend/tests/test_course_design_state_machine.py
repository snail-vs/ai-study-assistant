import asyncio
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.ai.providers.mock import MockTextProvider
from backend.db import Base
from backend.models import User
from backend.schemas import CourseDesignCommandRequest
from backend.services.course_design import CourseDesignConflict, CourseDesignInvalid, CourseDesignService
from backend.models import CourseDesignSession, LearningSpace


class CourseDesignStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(User(id="user-1", username="user-1", password_hash="hash"))
        self.db.commit()
        self.service = CourseDesignService(self.db, "user-1", MockTextProvider())

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def command(self, session, command_id, kind, payload=None, revision=None):
        return asyncio.run(self.service.execute(
            session.session_id,
            CourseDesignCommandRequest(
                commandId=command_id,
                expectedRevision=session.revision if revision is None else revision,
                type=kind,
                payload=payload or {},
            ),
        ))

    def test_explicit_state_flow_and_multiple_selection(self):
        session = asyncio.run(self.service.create("Kubernetes Operator"))
        self.assertEqual(session.state, "collecting_goals")
        session = self.command(session, "goals", "answer_question", {"answer": {
            "questionId": session.current_question.id,
            "selectedOptionIds": ["understand-core", "hands-on"],
            "customText": "能够独立开发一个 Operator",
        }})
        self.assertEqual(session.state, "collecting_background")
        self.assertEqual(session.brief.learning_goals, ["理解核心原理与架构", "能够动手完成实践"])

    def test_stale_revision_and_illegal_transition_are_rejected(self):
        session = asyncio.run(self.service.create("Python"))
        with self.assertRaises(CourseDesignConflict):
            self.command(session, "bad", "generate_outline")
        self.command(session, "goals", "complete_with_ai")
        with self.assertRaises(CourseDesignConflict):
            self.command(session, "stale", "complete_with_ai", revision=1)

    def test_duplicate_command_is_idempotent(self):
        session = asyncio.run(self.service.create("Python"))
        first = self.command(session, "same", "complete_with_ai")
        second = self.command(first, "same", "complete_with_ai")
        self.assertEqual(first.revision, second.revision)
        self.assertEqual(first.state, second.state)

    def test_outline_requires_scale_and_confirmation(self):
        session = asyncio.run(self.service.create("Python"))
        session = self.command(session, "goals", "complete_with_ai")
        session = self.command(session, "background", "complete_with_ai")
        session = self.command(session, "scale", "select_scale", {"courseScale": "quick"})
        session = self.command(session, "outline", "generate_outline")
        self.assertEqual(session.state, "reviewing_outline")
        with self.assertRaises(CourseDesignConflict):
            self.command(session, "course", "generate_course")
        session = self.command(session, "confirm", "confirm_outline")
        self.assertEqual(session.state, "outline_confirmed")

    def test_brief_change_invalidates_outline(self):
        session = asyncio.run(self.service.create("Python"))
        session = self.command(session, "goals", "complete_with_ai")
        session = self.command(session, "background", "complete_with_ai")
        session = self.command(session, "scale", "select_scale", {"courseScale": "quick"})
        session = self.command(session, "outline", "generate_outline")
        session = self.command(session, "back", "go_back")
        session = self.command(session, "edit", "update_brief", {"brief": {"learningOutcome": "完成一个可运行项目"}})
        self.assertEqual(session.outline, [])
        with self.assertRaises(CourseDesignConflict):
            self.command(session, "confirm", "confirm_outline")

    def test_get_does_not_initialize_provider(self):
        session = asyncio.run(self.service.create("Python"))
        with patch("backend.services.course_design.restore_active_provider", side_effect=RuntimeError("provider unavailable")):
            lazy = CourseDesignService(self.db, "user-1")
            snapshot = lazy.get(session.session_id)
        self.assertEqual(snapshot.session_id, session.session_id)

    def test_revision_feedback_and_outline_guards(self):
        session = asyncio.run(self.service.create("Python"))
        session = self.command(session, "goals", "complete_with_ai")
        session = self.command(session, "background", "complete_with_ai")
        with self.assertRaises(CourseDesignInvalid):
            self.command(session, "outline", "generate_outline")
        session = self.command(session, "scale", "select_scale", {"courseScale": "quick"})
        session = self.command(session, "outline", "generate_outline")
        with self.assertRaises(CourseDesignInvalid):
            self.command(session, "revise", "revise_outline", {"feedback": "  "})

    def test_generation_commits_session_and_space_once_before_schedule(self):
        session = asyncio.run(self.service.create("Python"))
        session = self.command(session, "goals", "complete_with_ai")
        session = self.command(session, "background", "complete_with_ai")
        session = self.command(session, "scale", "select_scale", {"courseScale": "quick"})
        session = self.command(session, "outline", "generate_outline")
        session = self.command(session, "confirm", "confirm_outline")
        with patch("backend.services.course_design.schedule_course_generation") as schedule:
            result = self.command(session, "course", "generate_course")
        self.assertEqual(result.state, "course_queued")
        self.assertEqual(self.db.query(LearningSpace).count(), 1)
        self.assertEqual(schedule.call_args.args[3], result.brief.model_dump(by_alias=True))

    def test_agent_patch_and_question_target_are_rejected(self):
        class MalformedAgent(MockTextProvider):
            async def structured(self, messages, *, task, schema):
                result = await super().structured(messages, task=task, schema=schema)
                if task == "course_intake_state" and "evaluate_intake_answer" in messages[-1]["content"]:
                    result["briefPatch"]["topic"] = "另一个主题"
                    result["briefPatch"]["useCase"] = "不应接受"
                    result["nextQuestion"]["target"] = "learningGoals"
                return result

        service = CourseDesignService(self.db, "user-1", MalformedAgent())
        session = asyncio.run(service.create("Python"))
        with self.assertRaises(CourseDesignInvalid):
            asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
                commandId="malformed", expectedRevision=session.revision, type="answer_question",
                payload={"answer": {"questionId": session.current_question.id, "selectedOptionIds": ["understand-core"]}},
            )))

    def test_conflict_resolution_replaces_previous_selections(self):
        class ConflictResolutionProvider:
            def __init__(self):
                self.answers = 0

            async def structured(self, messages, *, task, schema):
                if task != "course_intake_state":
                    raise AssertionError(f"unexpected task: {task}")
                if "start_intake" in messages[-1]["content"]:
                    return {
                        "briefPatch": {},
                        "decision": {"type": "ask_follow_up", "nextStage": "collecting_goals"},
                        "nextQuestion": {
                            "id": "initial-goals", "stage": "collecting_goals", "target": "learningGoals",
                            "title": "你希望获得哪些能力？",
                            "options": [
                                {"id": "zero", "label": "完全零基础"},
                                {"id": "experienced", "label": "工作中用过 Go"},
                            ],
                        },
                    }
                if self.answers == 0:
                    self.answers += 1
                    return {
                        "briefPatch": {},
                        "decision": {"type": "ask_follow_up", "nextStage": "collecting_goals"},
                        "nextQuestion": {
                            "id": "resolve-go-level", "stage": "collecting_goals", "target": "learningGoals",
                            "title": "你既勾了零基础也勾了有经验，请选一个最贴近的情况。",
                            "options": [
                                {"id": "zero", "label": "完全零基础"},
                                {"id": "other-language", "label": "会其他语言，但没写过 Go"},
                                {"id": "experienced", "label": "工作中用过 Go"},
                            ],
                        },
                    }
                return {
                    "briefPatch": {"learningOutcome": "按合适起点学习 Go"},
                    "decision": {"type": "advance", "nextStage": "collecting_background"},
                    "nextQuestion": {
                        "id": "background", "stage": "collecting_background", "target": "priorKnowledgeLevels",
                        "title": "你目前有哪些相关基础？", "options": [],
                    },
                }

        provider = ConflictResolutionProvider()
        service = CourseDesignService(self.db, "user-1", provider)
        session = asyncio.run(service.create("Go"))
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="contradictory", expectedRevision=session.revision, type="answer_question", payload={"answer": {
                "questionId": session.current_question.id, "selectedOptionIds": ["zero", "experienced"],
            }},
        )))
        self.assertEqual(session.state, "collecting_goals")
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="resolve", expectedRevision=session.revision, type="answer_question", payload={"answer": {
                "questionId": session.current_question.id, "selectedOptionIds": ["other-language"],
            }},
        )))
        self.assertEqual(session.brief.learning_goals, ["会其他语言，但没写过 Go"])

    def test_repeated_follow_up_is_completed_instead_of_shown_again(self):
        class RepeatingQuestionProvider:
            def __init__(self):
                self.answer_payload = None

            async def structured(self, messages, *, task, schema):
                payload = json.loads(messages[-1]["content"])
                if payload.get("task") == "start_intake":
                    return {
                        "briefPatch": {},
                        "decision": {"type": "ask_follow_up", "nextStage": "collecting_goals"},
                        "nextQuestion": {
                            "id": "goals", "stage": "collecting_goals", "target": "learningGoals",
                            "title": "你希望获得哪些能力？",
                            "options": [{"id": "practice", "label": "完成实际练习"}],
                        },
                    }
                if payload.get("task") == "evaluate_intake_answer":
                    self.answer_payload = payload
                    return {
                        "briefPatch": {},
                        "decision": {"type": "ask_follow_up", "nextStage": "collecting_goals"},
                        "nextQuestion": {
                            "id": "same-goals", "stage": "collecting_goals", "target": "learningGoals",
                            "title": "你希望获得哪些能力？",
                            "options": [{"id": "practice", "label": "完成实际练习"}],
                        },
                    }
                if payload.get("task") == "complete_with_ai":
                    return await MockTextProvider().structured(messages, task=task, schema=schema)
                raise AssertionError(f"unexpected payload: {payload}")

        provider = RepeatingQuestionProvider()
        service = CourseDesignService(self.db, "user-1", provider)
        session = asyncio.run(service.create("Go"))
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="goals", expectedRevision=session.revision, type="answer_question",
            payload={"answer": {"questionId": session.current_question.id, "selectedOptionIds": ["practice"]}},
        )))
        self.assertEqual(provider.answer_payload["answeredQuestion"]["id"], "goals")
        self.assertEqual(session.state, "collecting_background")
        self.assertIn("完成实际练习", session.brief.learning_goals)
        self.assertNotEqual(session.current_question.title, "你希望获得哪些能力？")

    def test_missing_next_stage_question_uses_server_fallback(self):
        class MissingTransitionQuestionProvider:
            def __init__(self):
                self.calls = 0

            async def structured(self, messages, *, task, schema):
                self.calls += 1
                if self.calls == 1:
                    return await MockTextProvider().structured(messages, task=task, schema=schema)
                return {
                    "briefPatch": {"learningOutcome": "掌握 Go 基础"},
                    "decision": {"type": "advance", "nextStage": "collecting_background"},
                    "nextQuestion": None,
                }

        service = CourseDesignService(self.db, "user-1", MissingTransitionQuestionProvider())
        session = asyncio.run(service.create("Go"))
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="goals", expectedRevision=session.revision, type="answer_question",
            payload={"answer": {"questionId": session.current_question.id, "selectedOptionIds": ["understand-core"]}},
        )))
        self.assertEqual(session.state, "collecting_background")
        self.assertEqual(session.current_question.id, "collecting-background-fallback")

    def test_scale_question_is_replaced_with_background_fallback(self):
        class ScaleQuestionProvider:
            def __init__(self):
                self.calls = 0

            async def structured(self, _messages, *, task, schema):
                self.calls += 1
                if self.calls == 1:
                    return await MockTextProvider().structured(_messages, task=task, schema=schema)
                return {
                    "briefPatch": {"learningOutcome": "掌握 Go 基础"},
                    "decision": {"type": "advance", "nextStage": "collecting_background"},
                    "nextQuestion": {
                        "id": "wrong-scale", "stage": "collecting_background", "target": "priorKnowledgeLevels",
                        "title": "你希望以什么规模和节奏学习 Go？",
                        "options": [{"id": "quick", "label": "快速了解：2-3 节"}],
                    },
                }

        service = CourseDesignService(self.db, "user-1", ScaleQuestionProvider())
        session = asyncio.run(service.create("Go"))
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="goals", expectedRevision=session.revision, type="answer_question", payload={"answer": {
                "questionId": session.current_question.id, "selectedOptionIds": ["understand-core"],
            }},
        )))
        self.assertEqual(session.state, "collecting_background")
        self.assertEqual(session.current_question.id, "collecting-background-fallback")
        self.assertEqual(session.current_question.target, "priorKnowledgeLevels")
        self.assertNotIn("规模", session.current_question.title)

    def test_get_repairs_a_persisted_scale_question(self):
        session = asyncio.run(self.service.create("Go"))
        persisted = self.service._owned(session.session_id)
        persisted.state = "collecting_background"
        persisted.current_question = {
            "id": "wrong-scale", "stage": "collecting_background", "target": "priorKnowledgeLevels",
            "type": "multi_select_with_text", "title": "你希望以什么规模和节奏学习 Go？",
            "description": "", "options": [{"id": "quick", "label": "快速了解：2-3 节"}],
            "allowCustom": True, "minimumSelections": 0,
        }
        persisted.questions = {"collecting_background": persisted.current_question}
        self.db.commit()

        repaired = self.service.get(session.session_id)
        self.assertEqual(repaired.current_question.id, "collecting-background-fallback")
        self.assertEqual(repaired.current_question.options[0].id, "no-programming")

    def test_agent_returned_topic_is_ignored_during_intake(self):
        class TopicEchoProvider(MockTextProvider):
            async def structured(self, messages, *, task, schema):
                result = await super().structured(messages, task=task, schema=schema)
                if task == "course_intake_state":
                    result["briefPatch"]["topic"] = "另一个主题"
                return result

        service = CourseDesignService(self.db, "user-1", TopicEchoProvider())
        session = asyncio.run(service.create("Python"))
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="goals", expectedRevision=session.revision, type="complete_with_ai", payload={},
        )))
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="background", expectedRevision=session.revision, type="complete_with_ai", payload={},
        )))
        self.assertEqual(session.brief.topic, "Python")

    def test_background_answer_ignores_known_goal_fields(self):
        class CrossStageProvider(MockTextProvider):
            async def structured(self, messages, *, task, schema):
                result = await super().structured(messages, task=task, schema=schema)
                if task == "course_intake_state" and '"stage": "collecting_background"' in messages[-1]["content"] and ("evaluate_intake_answer" in messages[-1]["content"] or "complete_with_ai" in messages[-1]["content"]):
                    result["briefPatch"].update({"learningOutcome": "不应覆盖的目标", "learningGoals": ["不应覆盖的目标"]})
                return result

        service = CourseDesignService(self.db, "user-1", CrossStageProvider())
        session = asyncio.run(service.create("Python"))
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="goals", expectedRevision=session.revision, type="complete_with_ai", payload={},
        )))
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="background", expectedRevision=session.revision, type="answer_question",
            payload={"answer": {"questionId": session.current_question.id, "selectedOptionIds": [], "customText": "有 Python 基础"}},
        )))
        self.assertEqual(session.state, "reviewing_brief")
        self.assertNotEqual(session.brief.learning_outcome, "不应覆盖的目标")

        service = CourseDesignService(self.db, "user-1", CrossStageProvider())
        session = asyncio.run(service.create("Python"))
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="goals-2", expectedRevision=session.revision, type="complete_with_ai", payload={},
        )))
        session = asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
            commandId="background-2", expectedRevision=session.revision, type="complete_with_ai", payload={},
        )))
        self.assertEqual(session.state, "reviewing_brief")
        self.assertNotEqual(session.brief.learning_outcome, "不应覆盖的目标")

    def test_missing_summary_repair_failure_does_not_advance_session(self):
        class MissingSummaryProvider(MockTextProvider):
            async def structured(self, messages, *, task, schema):
                if task == "course_intake_state" and any(token in messages[-1]["content"] for token in ("evaluate_intake_answer", "repair_intake_state")):
                    return {
                        "briefPatch": {},
                        "decision": {"type": "advance", "nextStage": "collecting_background"},
                        "nextQuestion": {"id": "background-1", "stage": "collecting_background", "target": "priorKnowledgeLevels", "title": "基础？", "options": []},
                    }
                return await super().structured(messages, task=task, schema=schema)

        service = CourseDesignService(self.db, "user-1", MissingSummaryProvider())
        session = asyncio.run(service.create("Python"))
        revision = session.revision
        with self.assertRaises(CourseDesignInvalid):
            asyncio.run(service.execute(session.session_id, CourseDesignCommandRequest(
                commandId="missing-summary", expectedRevision=session.revision, type="answer_question",
                payload={"answer": {"questionId": session.current_question.id, "selectedOptionIds": ["understand-core"]}},
            )))
        persisted = service.get(session.session_id)
        self.assertEqual(persisted.revision, revision)
        self.assertEqual(persisted.state, "collecting_goals")

    def test_retry_requires_owned_failed_space_and_reuses_it(self):
        failed = LearningSpace(
            id="failed-space", user_id="user-1", title="旧课程", learning_goal="旧目标",
            generation_status="failed", generation_phase="failed", generation_error="provider",
        )
        active = LearningSpace(
            id="active-space", user_id="user-1", title="进行中", learning_goal="目标",
            generation_status="completed", generation_phase="completed",
        )
        self.db.add_all([failed, active])
        self.db.commit()
        retry = asyncio.run(self.service.create("Python", "failed-space"))
        retry = self.command(retry, "goals", "complete_with_ai")
        retry = self.command(retry, "background", "complete_with_ai")
        retry = self.command(retry, "scale", "select_scale", {"courseScale": "quick"})
        retry = self.command(retry, "outline", "generate_outline")
        retry = self.command(retry, "confirm", "confirm_outline")
        with patch("backend.services.course_design.schedule_course_generation"):
            result = self.command(retry, "course", "generate_course")
        self.assertEqual(result.operation["spaceId"], "failed-space")
        self.assertEqual(self.db.query(LearningSpace).count(), 2)
        self.assertEqual(self.db.get(LearningSpace, "failed-space").generation_status, "queued")
        with self.assertRaises(CourseDesignInvalid):
            asyncio.run(self.service.create("Python", "active-space"))
        with self.assertRaises(CourseDesignInvalid):
            asyncio.run(self.service.create("Python", "missing-space"))

    def test_legacy_create_shape_with_same_topic_is_accepted(self):
        class LegacyGateway(MockTextProvider):
            async def structured(self, messages, *, task, schema):
                return {
                    "stage": "collecting_goals", "ready": False,
                    "brief": {"topic": "Kubernetes Operator"},
                    "nextQuestion": {
                        "prompt": "你想获得哪些能力？",
                        "target": "learningGoals",
                        "options": [{"label": "理解原理", "value": "understand"}],
                        "allowCustomText": True,
                    },
                }

        service = CourseDesignService(self.db, "user-1", LegacyGateway())
        session = asyncio.run(service.create("Kubernetes Operator"))
        self.assertEqual(session.current_question.options[0].id, "understand")
        self.assertEqual(session.current_question.title, "你想获得哪些能力？")

    def test_agent_returned_topic_is_ignored_on_create_and_restart(self):
        class ChangedTopicGateway:
            async def structured(self, _messages, *, task, schema):
                return {
                    "stage": "collecting_goals", "ready": False,
                    "brief": {"topic": "另一主题"},
                    "nextQuestion": {"prompt": "问题", "target": "learningGoals", "options": []},
                }

        service = CourseDesignService(self.db, "user-1", ChangedTopicGateway())
        session = asyncio.run(service.create("Python"))
        self.assertEqual(session.brief.topic, "Python")

        restarted = self.command(session, "restart", "restart")
        self.assertEqual(restarted.brief.topic, "Python")

    def test_malformed_answer_and_complete_are_controlled(self):
        class MalformedAfterStart:
            def __init__(self):
                self.calls = 0

            async def structured(self, _messages, *, task, schema):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "stage": "collecting_goals", "ready": False,
                        "nextQuestion": {"prompt": "问题", "target": "learningGoals", "options": [{"value": "a"}]},
                    }
                return {"stage": "collecting_goals", "ready": False, "nextQuestion": {"options": [{"bad": True}]}}

        gateway = MalformedAfterStart()
        service = CourseDesignService(self.db, "user-1", gateway)
        session = asyncio.run(service.create("Python"))
        answer = CourseDesignCommandRequest(
            commandId="malformed-answer", expectedRevision=session.revision, type="answer_question",
            payload={"answer": {"questionId": session.current_question.id, "selectedOptionIds": ["a"]}},
        )
        with self.assertRaises(CourseDesignInvalid):
            asyncio.run(service.execute(session.session_id, answer))
        complete = CourseDesignCommandRequest(
            commandId="malformed-complete", expectedRevision=session.revision, type="complete_with_ai", payload={}
        )
        with self.assertRaises(CourseDesignInvalid):
            asyncio.run(service.execute(session.session_id, complete))


if __name__ == "__main__":
    unittest.main()
