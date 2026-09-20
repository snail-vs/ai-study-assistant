import asyncio
import unittest
from unittest.mock import patch

from backend.agents.course_intake_agent import CourseIntakeAgent, CourseIntakeInvalidResult
from backend.agents.outline_agent import CourseOutlineAgent
from backend.agents.language_policy import infer_response_language
from backend.ai.providers.mock import MockTextProvider
from backend.course_design_api import course_design_outline, course_design_turn
from backend.schemas import CourseBrief, CourseDesignTurnRequest, CourseOutlineRequest, CreateLearningSpaceRequest


class FakeGateway:
    async def structured(self, _messages, *, task, schema):
        self.task = task
        return {
            "brief": {"topic": "Python", "learningOutcome": "完成数据分析"},
            "assistant_message": "你的基础如何？",
            "question": "你的基础如何？",
            "quick_options": ["零基础", "会其他语言"],
            "ready": False,
            "recommended_scale": "standard",
            "outline": [],
        }


class MissingQuestionGateway(FakeGateway):
    async def structured(self, _messages, *, task, schema):
        result = await super().structured(_messages, task=task, schema=schema)
        result["assistant_message"] = "我了解了你的方向。"
        result["question"] = None
        return result


class LegacyStateGateway:
    async def structured(self, _messages, *, task, schema):
        return {
            "stage": "collecting_goals",
            "ready": False,
            "brief": {"topic": "Kubernetes Operator"},
            "nextQuestion": {
                "question": "你想获得哪些能力？",
                "target": "learningGoals",
                "options": [{"value": "理解原理"}, {"value": "完成实践"}],
                "allowCustomText": True,
            },
            "recommendedScale": "standard",
        }


class CapturingLegacyGateway(LegacyStateGateway):
    def __init__(self):
        self.messages = None

    async def structured(self, messages, *, task, schema):
        self.messages = messages
        return await super().structured(messages, task=task, schema=schema)


class InvalidStateGateway:
    async def structured(self, _messages, *, task, schema):
        return {"stage": "collecting_goals", "ready": False, "nextQuestion": {"options": [{"bad": True}]}}


class StageShapeGateway:
    def __init__(self, *, top_stage=None, question_stage=None, decision_stage=None, include_type=True):
        self.top_stage = top_stage
        self.question_stage = question_stage
        self.decision_stage = decision_stage
        self.include_type = include_type

    async def structured(self, _messages, *, task, schema):
        result = {
            "stage": self.top_stage or "collecting_goals",
            "ready": False,
            "decision": {"nextStage": self.decision_stage or "collecting_goals"},
            "nextQuestion": {
                "prompt": "问题",
                "stage": self.question_stage or "collecting_goals",
                "target": "learningGoals",
                "options": [],
            },
        }
        if self.include_type:
            result["decision"]["type"] = "ask_follow_up"
        return result


class CourseIntakeTests(unittest.TestCase):
    def test_agent_merges_existing_brief_and_uses_intake_task(self):
        gateway = FakeGateway()
        result = asyncio.run(CourseIntakeAgent(gateway).turn([], {
            "topic": "Python",
            "learningGoals": ["完成部署实践", "能够排查问题"],
            "priorKnowledgeLevels": ["了解基本概念", "有相关实践"],
            "learningGoalDetails": "需要一个真实项目",
            "priorKnowledgeDetails": "用过 Linux",
        }))
        self.assertEqual(gateway.task, "course_intake")
        self.assertEqual(result.brief["topic"], "Python")
        self.assertEqual(result.brief["learningOutcome"], "完成数据分析")
        self.assertEqual(result.brief["learningGoals"], ["完成部署实践", "能够排查问题"])
        self.assertEqual(result.brief["priorKnowledgeLevels"], ["了解基本概念", "有相关实践"])
        self.assertEqual(result.brief["learningGoalDetails"], "需要一个真实项目")
        self.assertEqual(result.brief["priorKnowledgeDetails"], "用过 Linux")

    def test_mock_provider_returns_a_valid_intake_result(self):
        result = asyncio.run(CourseIntakeAgent(MockTextProvider()).turn([], {"topic": "Python"}))
        self.assertEqual(result.brief["topic"], "Python")
        self.assertFalse(result.ready)
        self.assertTrue(result.question)
        self.assertTrue(result.quick_options)
        self.assertEqual(result.recommended_scale, "standard")

    def test_legacy_state_payload_is_normalized_at_agent_boundary(self):
        result = asyncio.run(CourseIntakeAgent(LegacyStateGateway()).start(topic="Kubernetes Operator"))
        self.assertEqual(result.decision.type, "ask_follow_up")
        self.assertEqual(result.next_question.id, "collecting_goals-question")
        self.assertEqual([item.id for item in result.next_question.options], ["理解原理", "完成实践"])
        self.assertTrue(result.next_question.allow_custom)

    def test_truly_invalid_state_payload_is_rejected(self):
        with self.assertRaises(CourseIntakeInvalidResult):
            asyncio.run(CourseIntakeAgent(InvalidStateGateway()).start(topic="Python"))

    def test_unknown_stage_values_are_rejected(self):
        for gateway in (
            StageShapeGateway(top_stage="collecting_goalz"),
            StageShapeGateway(question_stage="collecting_goalz"),
            StageShapeGateway(decision_stage="reviewing_outlinex"),
        ):
            with self.assertRaises(CourseIntakeInvalidResult):
                asyncio.run(CourseIntakeAgent(gateway).start(topic="Python"))

    def test_legacy_prior_knowledge_stage_alias_is_normalized(self):
        gateway = StageShapeGateway(
            top_stage="collecting_prior_knowledge",
            question_stage="collecting_prior_knowledge",
            decision_stage="collecting_prior_knowledge",
        )
        result = asyncio.run(CourseIntakeAgent(gateway).start(topic="Python"))
        self.assertEqual(result.decision.next_stage, "collecting_background")
        self.assertEqual(result.next_question.stage, "collecting_background")

    def test_missing_decision_type_uses_next_stage_transition(self):
        gateway = StageShapeGateway(
            top_stage="collecting_background",
            question_stage="collecting_background",
            decision_stage="collecting_background",
            include_type=False,
        )
        result = asyncio.run(CourseIntakeAgent(gateway).answer(
            stage="collecting_goals", brief={}, selected_labels=["实践"]
        ))
        self.assertEqual(result.decision.type, "advance")
        self.assertEqual(result.decision.next_stage, "collecting_background")

    def test_response_language_policy_handles_technical_terms(self):
        self.assertEqual(infer_response_language("学习 Kubernetes Operator 和 CRD"), "zh-CN")
        self.assertEqual(infer_response_language("k8s operator"), "zh-CN")
        self.assertEqual(infer_response_language("Learn Kubernetes Operator and CRD"), "zh-CN")
        self.assertEqual(infer_response_language("Aprender Kubernetes y CRD"), "zh-CN")
        self.assertEqual(infer_response_language("私はKubernetesを学びたい"), "zh-CN")
        self.assertEqual(infer_response_language("Kubernetes 오퍼레이터를 배우고 싶어요"), "zh-CN")

    def test_intake_agent_sends_explicit_response_language(self):
        gateway = CapturingLegacyGateway()
        asyncio.run(CourseIntakeAgent(gateway).start(topic="学习 Kubernetes Operator"))
        self.assertIn("responseLanguage=zh-CN", gateway.messages[0]["content"])
        self.assertIn('"responseLanguage": "zh-CN"', gateway.messages[1]["content"])

    def test_answer_language_uses_topic_not_generated_labels(self):
        gateway = CapturingLegacyGateway()
        asyncio.run(CourseIntakeAgent(gateway).answer(
            stage="collecting_goals",
            brief={"topic": "Learn Kubernetes Operator"},
            selected_labels=["理解核心原理", "完成实践"],
        ))
        self.assertIn("responseLanguage=zh-CN", gateway.messages[0]["content"])
        self.assertIn('"responseLanguage": "zh-CN"', gateway.messages[1]["content"])

        gateway = CapturingLegacyGateway()
        asyncio.run(CourseIntakeAgent(gateway).answer(
            stage="collecting_goals",
            brief={"topic": "学习 Kubernetes Operator"},
            selected_labels=["Understand Kubernetes architecture", "Write a CRD"],
        ))
        self.assertIn("responseLanguage=zh-CN", gateway.messages[0]["content"])
        self.assertIn('"responseLanguage": "zh-CN"', gateway.messages[1]["content"])

    def test_outline_agent_sends_language_policy(self):
        class OutlineCapture:
            def __init__(self):
                self.messages = None

            async def structured(self, messages, *, task, schema):
                self.messages = messages
                return {"outline": [{"title": f"OpenStack：阶段 {i}", "objective": f"掌握能力 {i}"} for i in range(1, 4)]}

        gateway = OutlineCapture()
        asyncio.run(CourseOutlineAgent(gateway).generate({"topic": "系统学习 OpenStack"}, "quick"))
        self.assertIn("responseLanguage=zh-CN", gateway.messages[0]["content"])
        self.assertIn("responseLanguage=zh-CN", gateway.messages[1]["content"])

    def test_outline_revision_language_uses_topic_not_feedback(self):
        class OutlineCapture:
            def __init__(self):
                self.messages = None

            async def structured(self, messages, *, task, schema):
                self.messages = messages
                return {"outline": [
                    {"title": "OpenStack: Overview", "objective": "Understand the architecture"},
                    {"title": "OpenStack: Core concepts", "objective": "Understand the core concepts"},
                    {"title": "OpenStack: Practice", "objective": "Apply the concepts"},
                ], "assistant_message": "Updated."}

        gateway = OutlineCapture()
        asyncio.run(CourseOutlineAgent(gateway).revise(
            {"topic": "Learn OpenStack"}, "quick", [{"title": "OpenStack: Overview", "objective": "Understand the architecture"}],
            "请改成更适合初学者",
            [],
        ))
        self.assertIn("responseLanguage=zh-CN", gateway.messages[0]["content"])
        self.assertIn("responseLanguage=zh-CN", gateway.messages[1]["content"])

    def test_explicit_scale_does_not_overwrite_model_recommendation(self):
        gateway = FakeGateway()
        result = asyncio.run(CourseIntakeAgent(gateway).turn([], {"topic": "Python"}, "quick"))
        self.assertEqual(result.recommended_scale, "standard")

    def test_creation_defaults_to_standard_scale(self):
        request = CourseDesignTurnRequest.model_validate({"messages": []})
        brief = request.brief or CourseBrief()
        self.assertEqual(request.course_scale, None)
        self.assertEqual(brief.topic, "")
        self.assertEqual(CreateLearningSpaceRequest(title="x", learningGoal="y").course_scale, "standard")

    def test_course_brief_accepts_structured_profile_fields_and_legacy_fields(self):
        brief = CourseBrief.model_validate({
            "learningGoals": ["掌握核心原理", "完成部署实践"],
            "learningGoalDetails": "希望能独立排查问题",
            "priorKnowledge": "接触过 Linux",
            "priorKnowledgeLevels": ["了解基本概念", "有相关实践"],
            "priorKnowledgeDetails": "做过虚拟机部署",
        })
        self.assertEqual(brief.learning_goals, ["掌握核心原理", "完成部署实践"])
        self.assertEqual(brief.prior_knowledge_levels, ["了解基本概念", "有相关实践"])
        self.assertEqual(brief.model_dump(by_alias=True)["priorKnowledge"], "接触过 Linux")

    def test_first_turn_does_not_return_a_fake_outline(self):
        from backend import course_design_api

        request = CourseDesignTurnRequest(messages=[])
        with patch.object(course_design_api, "restore_active_provider", return_value=FakeGateway()), patch.object(
            course_design_api, "current_user_id", return_value="user-1"
        ):
            response = asyncio.run(course_design_turn(request, db=object()))
        self.assertFalse(response.ready)
        self.assertEqual(response.turn, 0)
        self.assertEqual(response.outline, [])

    def test_skip_finishes_intake_without_an_outline(self):
        from backend import course_design_api

        request = CourseDesignTurnRequest(skip=True, brief=CourseBrief(topic="Python"))
        with patch.object(course_design_api, "restore_active_provider", return_value=FakeGateway()), patch.object(
            course_design_api, "current_user_id", return_value="user-1"
        ):
            response = asyncio.run(course_design_turn(request, db=object()))
        self.assertTrue(response.ready)
        self.assertEqual(response.course_scale, "standard")
        self.assertEqual(response.outline, [])

    def test_outline_endpoint_generates_scale_specific_outline(self):
        from backend import course_design_api

        class TopicGateway(FakeGateway):
            async def structured(self, _messages, *, task, schema):
                result = await super().structured(_messages, task=task, schema=schema)
                result["brief"]["topic"] = "OpenStack"
                return result

        class OutlineGateway(TopicGateway):
            async def structured(self, _messages, *, task, schema):
                if task == "course_outline":
                    count = 3 if "课程规模：quick" in _messages[-1]["content"] else 10 if "课程规模：series" in _messages[-1]["content"] else 6
                    return {"outline": [{"title": f"OpenStack：第 {i + 1} 阶段", "objective": f"掌握 OpenStack 能力 {i + 1}"} for i in range(count)]}
                return await super().structured(_messages, task=task, schema=schema)

        for scale, expected_count in (("quick", 3), ("standard", 6), ("series", 10)):
            request = CourseOutlineRequest(courseScale=scale, brief=CourseBrief(topic="OpenStack"))
            with patch.object(course_design_api, "restore_active_provider", return_value=OutlineGateway()), patch.object(
                course_design_api, "current_user_id", return_value="user-1"
            ):
                response = asyncio.run(course_design_outline(request, db=object()))
            self.assertEqual(len(response.outline), expected_count)
            self.assertEqual(len({item.objective for item in response.outline}), expected_count)
            self.assertTrue(all(item.title.startswith("OpenStack：") for item in response.outline))

    def test_outline_endpoint_rejects_repeated_objectives(self):
        from backend import course_design_api

        class RepeatedOutlineGateway(FakeGateway):
            async def structured(self, _messages, *, task, schema):
                result = await super().structured(_messages, task=task, schema=schema)
                if task == "course_outline":
                    return {"outline": [{"title": f"模块 {i}", "objective": "重复目标"} for i in range(3)]}
                return result

        request = CourseOutlineRequest(courseScale="quick", brief=CourseBrief(topic="OpenStack"))
        with patch.object(course_design_api, "restore_active_provider", return_value=RepeatedOutlineGateway()), patch.object(
            course_design_api, "current_user_id", return_value="user-1"
        ):
            with self.assertRaises(Exception) as caught:
                asyncio.run(course_design_outline(request, db=object()))
        self.assertIn("互不重复", str(caught.exception))

    def test_non_ready_response_always_has_a_real_question(self):
        from backend import course_design_api

        request = CourseDesignTurnRequest(messages=[])
        with patch.object(course_design_api, "restore_active_provider", return_value=MissingQuestionGateway()), patch.object(
            course_design_api, "current_user_id", return_value="user-1"
        ):
            response = asyncio.run(course_design_turn(request, db=object()))
        self.assertEqual(response.assistant_message, "我了解了你的方向。")
        self.assertEqual(response.question, "为了更准确地设计课程，请告诉我你希望学完后能够完成什么？")


if __name__ == "__main__":
    unittest.main()
