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
        return {"action": "NORMAL_ANSWER", "reply": "这是 Mock 结构化回复。", "proposal": None}
