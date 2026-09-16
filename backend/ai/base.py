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
    """A provider failed or returned an invalid response.

    ``message`` intentionally remains the provider's raw message for logs and
    debugging.  The category is stable and safe for the UI to consume.
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = "provider_error",
        status_code: int | None = None,
        provider_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.provider_code = provider_code


class AICompatibilityError(AIProviderError):
    """The selected model cannot satisfy a requested protocol or schema."""
