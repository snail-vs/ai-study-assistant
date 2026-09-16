from collections.abc import AsyncIterator, Sequence
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
        return {
            "title": "Mock 学习知识卡",
            "summary": "用于本地开发验证的知识卡。",
            "sections": [
                {"title": "核心概念", "content_markdown": "## 核心概念\n\n这是 Mock 内容。"}
            ],
        }
