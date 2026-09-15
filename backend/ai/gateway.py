from collections.abc import AsyncIterator, Sequence
from typing import Any

from .base import TextProvider
from .registry import create_text_provider


class AIGateway:
    def __init__(self, provider: TextProvider | None = None) -> None:
        self.provider = provider or create_text_provider()

    def stream_text(
        self, messages: Sequence[dict[str, str]], *, task: str
    ) -> AsyncIterator[str]:
        return self.provider.stream_text(messages, task=task)

    async def structured(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.provider.structured(messages, task=task, schema=schema)
