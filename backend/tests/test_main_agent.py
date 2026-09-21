import asyncio
import unittest

from backend.agents.main_agent import MainAgent


class PlanRepairGateway:
    def __init__(self, *, repair_succeeds: bool):
        self.repair_succeeds = repair_succeeds
        self.plan_calls = 0

    async def structured(self, _messages, *, task, schema):
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


if __name__ == "__main__":
    unittest.main()
