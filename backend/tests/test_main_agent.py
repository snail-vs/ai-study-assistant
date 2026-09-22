import asyncio
import json
import unittest

from backend.agents.main_agent import MainAgent
from backend.agents.schemas import CourseReviewSectionSnapshot, KnowledgeCardPlanDraft, SectionPlanDraft
from backend.schemas import CourseBrief, CourseOutlineItem


class PlanRepairGateway:
    def __init__(self, *, repair_succeeds: bool):
        self.repair_succeeds = repair_succeeds
        self.plan_calls = 0
        self.calls = []

    async def structured(self, messages, *, task, schema):
        self.calls.append((task, messages))
        if task == "course_plan":
            self.plan_calls += 1
            if self.plan_calls == 1 or not self.repair_succeeds:
                return {"title": "Go 入门", "summary": "构建小型服务"}
            return {
                "title": "Go 入门",
                "summary": "构建小型服务",
                "sections": [
                    {"title": "基础语法", "teaching_objective": "理解 Go 基础语法", "content_type": "concept"},
                    {"title": "实战服务", "teaching_objective": "构建一个小型服务", "content_type": "practice"},
                ],
            }
        if task == "section_content":
            return {"content_markdown": "正文"}
        if task == "section_review":
            return {
                "correctness": 4,
                "goal_alignment": 4,
                "clarity": 4,
                "information_density": 4,
            }
        if task == "section_summary":
            payload = json.loads(messages[-1]["content"])
            title = payload["sectionContext"]["current_section"]["title"]
            return {
                "actually_taught": [title],
                "examples_used": [f"{title}示例"],
                "summary": f"已讲授{title}",
            }
        if task == "course_review":
            return {
                "goal_coverage": 4,
                "progression": 4,
                "prerequisite_order": 4,
                "redundancy": 4,
                "difficulty_curve": 4,
                "practice_coverage": 4,
                "assessment_alignment": 4,
                "personalization": 4,
            }
        raise AssertionError(f"unexpected task: {task}")


class MainAgentTests(unittest.TestCase):
    def test_repairs_missing_plan_sections_once(self):
        gateway = PlanRepairGateway(repair_succeeds=True)

        result = asyncio.run(MainAgent(gateway).create_card("学习 Go", scale="quick"))

        self.assertEqual(gateway.plan_calls, 2)
        self.assertEqual(len(result.sections), 2)

    def test_rejects_plan_when_repair_still_lacks_sections(self):
        gateway = PlanRepairGateway(repair_succeeds=False)

        with self.assertRaisesRegex(ValueError, "模型修复后仍未生成有效课程规划"):
            asyncio.run(MainAgent(gateway).create_card("学习 Go", scale="quick"))
        self.assertEqual(gateway.plan_calls, 2)

    def test_accepts_pydantic_brief_and_outline_from_retry_request(self):
        gateway = PlanRepairGateway(repair_succeeds=True)

        result = asyncio.run(MainAgent(gateway).create_card(
            "学习 Go",
            CourseBrief(
                topic="Go",
                learning_outcome="完成服务",
                prior_knowledge="了解基本语法",
                preferred_style=["实战"],
            ),
            "quick",
            [
                CourseOutlineItem(title="基础", objective="理解语法", role="concept", keyConcepts=["变量"]),
                CourseOutlineItem(title="实战", objective="完成服务", role="practice", prerequisites=["变量"]),
            ],
        ))

        self.assertEqual(len(result.sections), 2)
        self.assertEqual(gateway.plan_calls, 0)
        self.assertEqual([section.content_type for section in result.sections], ["concept", "practice"])
        second_author_call = [call for call in gateway.calls if call[0] == "section_content"][1]
        payload = json.loads(second_author_call[1][-1]["content"])
        context = payload["sectionContext"]
        self.assertEqual(context["learner_brief"]["priorKnowledge"], "了解基本语法")
        self.assertEqual(context["learner_brief"]["preferredStyle"], ["实战"])
        self.assertEqual(context["previous_actual_summary"]["summary"], "已讲授基础")
        self.assertEqual(context["taught_concepts"], ["基础"])
        self.assertEqual(context["examples_already_used"], ["基础示例"])

    def test_does_not_append_generic_fillers_after_short_repair(self):
        class ShortPlanGateway(PlanRepairGateway):
            async def structured(self, messages, *, task, schema):
                if task == "course_plan":
                    self.plan_calls += 1
                    return {
                        "title": "Go 入门",
                        "summary": "聚焦一个真实目标",
                        "sections": [{
                            "title": "最小服务",
                            "teaching_objective": "完成最小服务",
                            "content_type": "practice",
                        }],
                    }
                return await super().structured(messages, task=task, schema=schema)

        gateway = ShortPlanGateway(repair_succeeds=True)
        result = asyncio.run(MainAgent(gateway).create_card("学习 Go", scale="quick"))

        self.assertEqual(gateway.plan_calls, 2)
        self.assertEqual([section.title for section in result.sections], ["最小服务"])

    def test_course_review_uses_summaries_without_section_body(self):
        gateway = PlanRepairGateway(repair_succeeds=True)
        plan = KnowledgeCardPlanDraft(
            title="Go",
            summary="学习 Go",
            sections=[SectionPlanDraft(title="变量", teaching_objective="理解变量")],
        )
        review = asyncio.run(MainAgent(gateway).review_course(
            plan,
            {"topic": "Go", "priorKnowledge": "初学者"},
            [CourseReviewSectionSnapshot(
                order_index=0,
                title="变量",
                plan={"key_concepts": ["变量"]},
                actual_summary={"actually_taught": ["变量"]},
                quality_report={"quality_status": "passed"},
            )],
            language="zh",
        ))

        self.assertFalse(review.needs_revision)
        call = next(call for call in gateway.calls if call[0] == "course_review")
        payload = json.loads(call[1][-1]["content"])
        self.assertIn("sectionSummaries", payload)
        self.assertNotIn("contentMarkdown", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
