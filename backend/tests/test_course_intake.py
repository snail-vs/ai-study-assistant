import asyncio
import unittest
from unittest.mock import patch

from backend.agents.course_intake_agent import CourseIntakeAgent
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


class CourseIntakeTests(unittest.TestCase):
    def test_agent_merges_existing_brief_and_uses_intake_task(self):
        gateway = FakeGateway()
        result = asyncio.run(CourseIntakeAgent(gateway).turn([], {"topic": "Python"}))
        self.assertEqual(gateway.task, "course_intake")
        self.assertEqual(result.brief["topic"], "Python")
        self.assertEqual(result.brief["learningOutcome"], "完成数据分析")

    def test_mock_provider_returns_a_valid_intake_result(self):
        result = asyncio.run(CourseIntakeAgent(MockTextProvider()).turn([], {"topic": "Python"}))
        self.assertEqual(result.brief["topic"], "Python")
        self.assertFalse(result.ready)
        self.assertTrue(result.question)
        self.assertTrue(result.quick_options)
        self.assertEqual(result.recommended_scale, "standard")

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
