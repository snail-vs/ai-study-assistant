from collections.abc import AsyncIterator, Sequence
from typing import Any
from time import perf_counter

from .base import TextProvider
from .registry import create_text_provider


class AIGateway:
    def __init__(self, provider: TextProvider | None = None, *, user_id: str | None = None) -> None:
        self.provider = provider or create_text_provider()
        self.task_providers: dict[str, TextProvider] = {}
        self.user_id = user_id

    def configure(self, provider: TextProvider, task_providers: dict[str, TextProvider] | None = None) -> None:
        self.provider = provider
        self.task_providers = task_providers or {}

    def select_model(self, model: str) -> None:
        if not hasattr(self.provider, "model"):
            raise ValueError("Current provider does not expose model selection")
        self.provider.model = model

    def stream_text(
        self, messages: Sequence[dict[str, str]], *, task: str
    ) -> AsyncIterator[str]:
        provider = self.task_providers.get(task, self.provider)
        async def observed() -> AsyncIterator[str]:
            started = perf_counter()
            try:
                setattr(provider, "last_usage", {})
            except (AttributeError, TypeError):
                pass
            try:
                async for delta in provider.stream_text(messages, task=task):
                    yield delta
            except Exception:
                self._record(task, provider, False, started)
                raise
            else:
                self._record(task, provider, True, started)
        return observed()

    async def structured(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        provider = self.task_providers.get(task, self.provider)
        started = perf_counter()
        try:
            setattr(provider, "last_usage", {})
        except (AttributeError, TypeError):
            pass
        try:
            result = await provider.structured(messages, task=task, schema=schema)
        except Exception:
            self._record(task, provider, False, started)
            raise
        self._record(task, provider, True, started)
        return result

    def _record(self, task: str, provider: TextProvider, succeeded: bool, started: float) -> None:
        from ..services.ai_usage import record_usage
        usage = getattr(provider, "last_usage", {}) or {}
        record_usage(user_id=self.user_id, task=task,
            provider_name=getattr(provider, "provider_name", provider.__class__.__name__),
            model_id=getattr(provider, "model", None), succeeded=succeeded,
            duration_ms=round((perf_counter() - started) * 1000),
            input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"))
