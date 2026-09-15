from collections.abc import AsyncIterator, Sequence
from typing import Any

from .base import TextProvider
from .registry import create_text_provider


class AIGateway:
    def __init__(self, provider: TextProvider | None = None) -> None:
        self.provider = provider or create_text_provider()

    def configure(self, provider: TextProvider) -> None:
        self.provider = provider

    def select_model(self, model: str) -> None:
        if not hasattr(self.provider, "model"):
            raise ValueError("Current provider does not expose model selection")
        self.provider.model = model

    def stream_text(
        self, messages: Sequence[dict[str, str]], *, task: str
    ) -> AsyncIterator[str]:
        return self.provider.stream_text(messages, task=task)

    async def structured(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.provider.structured(messages, task=task, schema=schema)
