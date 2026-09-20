from collections.abc import AsyncIterator, Sequence
import json
import re
from typing import Any


class MockTextProvider:
    async def stream_text(
        self, messages: Sequence[dict[str, str]], *, task: str
    ) -> AsyncIterator[str]:
        content = messages[-1]["content"] if messages else ""
        reply = f"Mock 回复（{task}）：我收到了你的问题：{content}"
        for word in reply.split(" "):
            yield word + " "

    async def structured(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        if task == "course_intake":
            # CourseIntakeAgent embeds the current brief in the user prompt.
            # Keep the mock provider useful for local/demo flows by preserving
            # that topic while returning the complete intake contract.
            prompt = messages[-1]["content"] if messages else ""
            current: dict[str, Any] = {}
            match = re.search(r"已有 brief：(.+?)\n对话：", prompt, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                    if isinstance(parsed, dict):
                        current = parsed
                except json.JSONDecodeError:
                    pass
            topic = current.get("topic") or "Mock 课程主题"
            return {
                "brief": {
                    "topic": topic,
                    "learningOutcome": current.get("learningOutcome") or "理解并应用核心概念",
                    "learningGoals": current.get("learningGoals", []),
                    "learningGoalDetails": current.get("learningGoalDetails", ""),
                    "priorKnowledgeLevels": current.get("priorKnowledgeLevels", []),
                    "priorKnowledgeDetails": current.get("priorKnowledgeDetails", ""),
                    "priorKnowledge": current.get("priorKnowledge", ""),
                },
                "assistant_message": "你目前对这个主题的基础如何？",
                "question": "你目前对这个主题的基础如何？",
                "quick_options": ["零基础", "了解一些", "已有实践经验"],
                "ready": False,
                "recommended_scale": "standard",
                "outline": [],
            }
        if task == "course_intake_state":
            prompt = messages[-1]["content"] if messages else ""
            try:
                payload = json.loads(prompt)
            except json.JSONDecodeError:
                payload = {}
            stage = payload.get("stage", "collecting_goals")
            topic = payload.get("topic") or payload.get("brief", {}).get("topic") or "Mock 课程主题"
            if payload.get("task") == "start_intake":
                stage = "collecting_goals"
            if payload.get("task") == "complete_with_ai" and stage == "collecting_goals":
                return {
                    "briefPatch": {"learningGoals": ["理解核心原理与架构"], "learningGoalDetails": "由 AI 补全学习目标", "learningOutcome": f"掌握 {payload.get('brief', {}).get('topic') or '主题'} 核心原理并完成实践"},
                    "decision": {"type": "advance", "nextStage": "collecting_background"},
                    "assistantMessage": "接下来了解你的个人基础。",
                    "nextQuestion": {
                        "id": "background-1", "stage": "collecting_background", "target": "priorKnowledgeLevels",
                        "type": "multi_select_with_text", "title": "你目前具备哪些相关基础？",
                        "description": "可以多选，也可以补充说明。", "options": [],
                        "allowCustom": True, "minimumSelections": 0,
                    }, "recommendedScale": "standard",
                }
            if payload.get("task") == "complete_with_ai" and stage == "collecting_background":
                return {
                    "briefPatch": {"priorKnowledgeLevels": ["已有相关基础"], "priorKnowledgeDetails": "由 AI 补全个人基础", "priorKnowledge": "具备相关基础"},
                    "decision": {"type": "advance", "nextStage": "reviewing_brief"},
                    "assistantMessage": "需求信息已经比较清楚，请确认课程摘要和规模。",
                    "nextQuestion": None, "recommendedScale": "standard",
                }
            if stage == "collecting_goals":
                has_answer = bool(payload.get("answer", {}).get("selectedLabels") or payload.get("answer", {}).get("customText"))
                next_stage = "collecting_background" if has_answer and payload.get("task") == "evaluate_intake_answer" else "collecting_goals"
                return {
                    "briefPatch": {"learningOutcome": f"掌握 {topic} 核心原理并完成实践"} if has_answer else {},
                    "decision": {"type": "advance", "nextStage": next_stage},
                    "assistantMessage": f"你希望通过 {topic} 课程获得哪些能力？可以多选，也可以补充说明。",
                    "nextQuestion": {
                        "id": "background-1" if next_stage == "collecting_background" else "goals-1", "stage": next_stage, "target": "priorKnowledgeLevels" if next_stage == "collecting_background" else "learningGoals",
                        "type": "multi_select_with_text", "title": f"你希望通过 {topic} 获得哪些能力？",
                        "description": "可以多选，也可以输入自己的目标。",
                        "options": [
                            {"id": "understand-core", "label": "理解核心原理与架构"},
                            {"id": "hands-on", "label": "能够动手完成实践"},
                            {"id": "troubleshoot", "label": "能够排查常见问题"},
                        ], "allowCustom": True, "minimumSelections": 0,
                    },
                    "recommendedScale": "standard",
                }
            return {
                "briefPatch": {"priorKnowledge": f"具备 {topic} 相关基础"},
                "decision": {"type": "advance", "nextStage": "reviewing_brief"},
                "assistantMessage": "需求信息已经比较清楚，请确认课程摘要和规模。",
                "nextQuestion": None,
                "recommendedScale": "standard",
            }
        if task == "course_outline":
            prompt = messages[-1]["content"] if messages else ""
            scale = "series" if "课程规模：series" in prompt else "quick" if "课程规模：quick" in prompt else "standard"
            count = {"quick": 3, "standard": 6, "series": 10}[scale]
            match = re.search(r'"topic"\s*:\s*"([^"]+)"', prompt)
            topic = match.group(1) if match else "Mock 课程主题"
            stages = ["主题全景", "基础概念", "工作机制", "动手实践", "常见问题", "综合应用", "方案取舍", "进阶优化", "项目拆解", "复盘检验"]
            return {"outline": [{"title": f"{topic}：{stages[i]}", "objective": f"掌握 {topic} 的第 {i + 1} 项学习能力"} for i in range(count)]}
        if task == "course_outline_revision":
            prompt = messages[-1]["content"] if messages else ""
            scale = "series" if "课程规模：series" in prompt else "quick" if "课程规模：quick" in prompt else "standard"
            count = {"quick": 3, "standard": 6, "series": 10}[scale]
            match = re.search(r'"topic"\s*:\s*"([^"]+)"', prompt)
            topic = match.group(1) if match else "Mock 课程主题"
            stages = ["主题全景", "基础概念", "工作机制", "动手实践", "常见问题", "综合应用", "方案取舍", "进阶优化", "项目拆解", "复盘检验"]
            return {"outline": [{"title": f"{topic}：{stages[i]}", "objective": f"掌握 {topic} 的第 {i + 1} 项学习能力"} for i in range(count)], "assistant_message": "已根据你的建议调整课程大纲。"}
        if task == "gap_diagnosis":
            question = messages[-1]["content"] if messages else ""
            gap = any(word in question for word in ("进程", "内核", "隔离", "namespace"))
            return {
                "reply": f"这是针对问题的 Mock 解释：{question}",
                "diagnosis": {
                    "hasKnowledgeGap": gap,
                    "missingTopics": ["Linux 进程与命名空间"] if gap else [],
                },
                "proposal": {
                    "title": "Linux 进程与命名空间",
                    "reason": "先理解进程视图，有助于理解容器隔离。",
                    "relation_type": "prerequisite",
                } if gap else None,
            }
        if task == "bridge_note":
            return {"content": "📌 认知打通：前置知识帮助你看清当前主题背后的底层机制。"}
        if task == "teacher_guidance":
            return {"content": "老师：这一节先抓住核心概念，再观察它和前后知识的关系。可以边读边记录你认为最重要的一点。"}
        if task == "course_plan":
            return {
                "title": "Mock 学习知识卡",
                "summary": "用于本地开发验证的知识卡。",
                "sections": [
                    {
                        "title": "核心概念",
                        "teaching_objective": "理解主题的核心定义与关键关系。",
                        "content_type": "concept",
                    },
                    {
                        "title": "理解检查",
                        "teaching_objective": "用简短问题检查是否掌握核心概念。",
                        "content_type": "practice",
                    },
                ],
            }
        if task == "section_content":
            prompt = messages[-1]["content"] if messages else ""
            return {"content_markdown": f"## 本节内容\n\n这是根据以下教学规划生成的 Mock 内容：\n\n{prompt}"}
        if task == "section_review":
            return {
                "correctness": 4,
                "goal_alignment": 4,
                "clarity": 4,
                "information_density": 4,
                "blocking_issues": [],
                "repair_instructions": [],
            }
        if task == "section_repair":
            return {"content_markdown": "## 核心解释\n\n这是修订后的紧凑课程内容。\n\n## 理解检查\n\n请用一句话复述核心关系。"}
        if task == "side_answer_plan":
            return {
                "intent": "definition",
                "direct_answer": "先回答当前问题的核心定义。",
                "key_points": ["只保留理解当前章节所需的信息"],
                "needs_example": False,
                "possible_knowledge_gap": False,
                "target_length": "short",
            }
        if task == "quiz_generation":
            return {
                "title": "理解检查",
                "objective": "检查是否理解本节核心概念。",
                "questions": [
                    {"id": "q1", "type": "single_choice", "prompt": "本节最核心的概念是什么？", "options": [{"id": "a", "text": "选项 A"}, {"id": "b", "text": "选项 B"}]},
                    {"id": "q2", "type": "true_false", "prompt": "只要记住术语就代表理解了本节。", "options": []},
                    {"id": "q3", "type": "single_choice", "prompt": "哪个说法更准确？", "options": [{"id": "a", "text": "选项 A"}, {"id": "b", "text": "选项 B"}]},
                    {"id": "q4", "type": "short_answer", "prompt": "请用一句话说明本节的核心关系。", "options": []},
                ],
                "answer_key": [
                    {"question_id": "q1", "answer": "a", "explanation": "这是本节的核心概念。"},
                    {"question_id": "q2", "answer": False, "explanation": "理解还需要能够解释关系和应用。"},
                    {"question_id": "q3", "answer": "b", "explanation": "该说法更完整。"},
                    {"question_id": "q4", "reference_answer": "能够说清本节核心关系。", "rubric": ["提到核心概念", "说明概念之间的关系"]},
                ],
            }
        if task == "quiz_evaluation":
            return {"score": 70, "feedback": "回答抓住了主要关系，但还可以补充关键条件。", "misconception": None}
        return {
            "title": "Mock 学习知识卡",
            "summary": "用于本地开发验证的知识卡。",
            "sections": [
                {"title": "核心概念", "content_markdown": "## 核心概念\n\n这是 Mock 内容。"}
            ],
        }
