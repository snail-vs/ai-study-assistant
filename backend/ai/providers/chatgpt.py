"""Provider adapter for ChatGPT Plus/Pro subscription models.

Calls the Codex backend (`chatgpt.com/backend-api/codex/responses`) with an
OAuth access token obtained through the device-code flow, adding the headers
and request shape the subscription endpoint requires. Expired tokens are
refreshed transparently (locally by expiry, or once on a server-side 401).
"""

import json
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

import httpx

from ..base import AIProviderError
from ..oauth_chatgpt import ChatGptCredential, ChatGptOAuthError, refresh_credential
from ..structured import parse_json_text, provider_error, strict_json_schema

CODEX_BASE_URL = "https://chatgpt.com/backend-api"
CODEX_ENDPOINT = f"{CODEX_BASE_URL}/codex/responses"
DEFAULT_CODEX_MODEL = "gpt-5.5"
DEFAULT_INSTRUCTIONS = "You are a helpful assistant."
# The subscription endpoint exposes a fixed Codex model catalog (no /models API).
CODEX_MODELS = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex-spark",
)

TokenRefreshCallback = Callable[[ChatGptCredential], None]


class ChatGptCodexProvider:
    """OpenAI Responses adapter backed by the ChatGPT subscription endpoint."""

    def __init__(
        self,
        model: str | None = None,
        credential: ChatGptCredential | None = None,
        *,
        on_token_refresh: TokenRefreshCallback | None = None,
        endpoint: str = CODEX_ENDPOINT,
    ) -> None:
        self.model = model or DEFAULT_CODEX_MODEL
        self.credential = credential
        self.on_token_refresh = on_token_refresh
        self.endpoint = endpoint

    async def list_models(self) -> list[str]:
        return list(CODEX_MODELS)

    def _headers(self) -> dict[str, str]:
        if self.credential is None:
            raise AIProviderError("ChatGPT 尚未登录", category="authentication")
        return {
            "Authorization": f"Bearer {self.credential.access_token}",
            "chatgpt-account-id": self.credential.account_id,
            "originator": "pi",
            "User-Agent": "studycenter",
            "OpenAI-Beta": "responses=experimental",
            "accept": "text/event-stream",
            "Content-Type": "application/json",
        }

    def _split_instructions(
        self, messages: Sequence[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        instructions = DEFAULT_INSTRUCTIONS
        input_items: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") == "system":
                content = message.get("content")
                if isinstance(content, str):
                    instructions = content
                continue
            input_items.append({"role": message.get("role"), "content": message.get("content")})
        return instructions, input_items

    def _payload(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        text_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        instructions, input_items = self._split_instructions(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "store": False,
            "stream": True,
            "instructions": instructions,
            "input": input_items,
            "include": ["reasoning.encrypted_content"],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "text": {"format": text_format} if text_format is not None else {"verbosity": "low"},
        }
        return payload

    async def _ensure_credential(self) -> None:
        if self.credential is None:
            raise AIProviderError(
                "ChatGPT 尚未登录，请先在模型设置中完成设备码登录", category="authentication"
            )
        if self.credential.is_expired():
            await self._refresh()

    async def _refresh(self) -> None:
        if self.credential is None or not self.credential.refresh_token:
            raise AIProviderError("ChatGPT 凭证已过期且无法刷新，请重新登录", category="authentication")
        try:
            updated = await refresh_credential(self.credential.refresh_token)
        except ChatGptOAuthError as exc:
            raise AIProviderError(str(exc), category="authentication") from exc
        self.credential = updated
        if self.on_token_refresh is not None:
            self.on_token_refresh(updated)

    async def _stream_payload(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        await self._ensure_credential()
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    async with client.stream(
                        "POST", self.endpoint, headers=self._headers(), json=payload
                    ) as response:
                        if response.status_code == 401 and attempt == 0:
                            await self._refresh()
                            continue
                        if response.status_code >= 400:
                            body = (await response.aread()).decode(errors="replace")
                            raise provider_error(response.status_code, body)
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if not data or data == "[DONE]":
                                continue
                            try:
                                event = json.loads(data)
                            except json.JSONDecodeError as exc:
                                raise AIProviderError(
                                    "Invalid ChatGPT Codex streaming response"
                                ) from exc
                            event_type = event.get("type")
                            if event_type == "response.output_text.delta":
                                delta = event.get("delta")
                                if delta:
                                    yield delta
                            elif event_type in ("error", "response.failed"):
                                raise AIProviderError(str(event.get("error") or event))
                        return
            except httpx.HTTPError as exc:
                raise AIProviderError(
                    f"ChatGPT Codex 连接失败: {exc}", category="provider_unavailable"
                ) from exc

    async def stream_text(
        self, messages: Sequence[dict[str, str]], *, task: str
    ) -> AsyncIterator[str]:
        payload = self._payload(messages)
        async for delta in self._stream_payload(payload):
            yield delta

    async def structured(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        candidates: list[dict[str, Any] | None] = [
            {"type": "json_schema", "name": task, "schema": strict_json_schema(schema), "strict": True},
            {"type": "json_object"},
            None,
        ]
        last_error: AIProviderError | None = None
        for text_format in candidates:
            try:
                payload = self._payload(messages, text_format=text_format)
                chunks: list[str] = []
                async for delta in self._stream_payload(payload):
                    chunks.append(delta)
                return parse_json_text("".join(chunks))
            except AIProviderError as exc:
                last_error = exc
                if exc.category != "schema_incompatible":
                    raise
        raise last_error or AIProviderError("ChatGPT Codex 结构化输出失败", category="invalid_response")
