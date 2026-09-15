from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol


class TextProvider(Protocol):
    async def stream_text(
        self, messages: Sequence[dict[str, str]], *, task: str
    ) -> AsyncIterator[str]: ...

    async def structured(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]: ...


class AIProviderError(RuntimeError):
    """A provider failed or returned an invalid response."""
