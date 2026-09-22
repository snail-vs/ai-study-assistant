"""Anthropic Messages API provider adapter.

Talks to any Anthropic Messages-compatible endpoint: Anthropic's own API,
OpenCode Zen (`/zen/v1/messages`), DeepSeek's gateway (`/anthropic/v1/messages`),
and similar. Auth is chosen from the key shape:

- ``sk-ant-oat...`` OAuth access token -> ``Authorization: Bearer`` plus the
  ``oauth-2025-04-20`` beta header (Claude Code subscription tokens).
- ``sk-ant-...`` API key -> ``x-api-key`` (Anthropic Console).
- anything else -> ``Authorization: Bearer`` (third-party gateways).
"""

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from ..base import AIProviderError
from ..capabilities import ModelCapabilities, capabilities_for_route
from ..model_routing import ModelRoute
from ..structured import parse_json_text, provider_error, strict_json_schema

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 8192
STRUCTURED_TOOL_NAME = "structured_output"
NON_RETRYABLE_CATEGORIES = {
    "authentication",
    "insufficient_balance",
    "rate_limited",
    "provider_unavailable",
}


class AnthropicMessagesProvider:
    """Provider adapter for the Anthropic Messages protocol."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        endpoint: str | None = None,
        protocol: str = "anthropic_messages",
        capabilities: ModelCapabilities | None = None,
        route: ModelRoute | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.protocol = protocol
        self.endpoint = endpoint or f"{self.base_url}/v1/messages"
        self.capabilities = capabilities or capabilities_for_route(
            route or ModelRoute("unknown", "anthropic", protocol, self.endpoint)
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept": "application/json",
        }
        if self.api_key.startswith("sk-ant-oat"):
            headers["authorization"] = f"Bearer {self.api_key}"
            headers["anthropic-beta"] = "oauth-2025-04-20"
            headers["user-agent"] = "claude-cli/2.1.220"
            headers["x-app"] = "cli"
        else:
            # Anthropic's own API, OpenCode Zen and DeepSeek's gateway all
            # accept x-api-key; Bearer is only for OAuth access tokens.
            headers["x-api-key"] = self.api_key
        return headers

    def _capture_usage(self, body: dict[str, Any]) -> None:
        usage = body.get("usage") or {}
        if not isinstance(usage, dict):
            return
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        self.last_usage = {
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": (input_tokens + output_tokens) if isinstance(input_tokens, int) and isinstance(output_tokens, int) else None,
        }

    def _models_url(self) -> str:
        if self.endpoint.endswith("/messages"):
            return f"{self.endpoint[: -len('/messages')]}/models"
        return f"{self.base_url}/v1/models"

    def _payload(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        stream: bool,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role == "system":
                if isinstance(content, str) and content:
                    system_parts.append(content)
                continue
            if role not in ("user", "assistant"):
                role = "user"
            converted.append({"role": role, "content": content if content is not None else ""})
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": converted,
            "stream": stream,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return payload

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(self._models_url(), headers=self._headers())
        if response.status_code >= 400:
            raise provider_error(response.status_code, response.text)
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise AIProviderError("Invalid model list response from provider") from exc
        items = body.get("data") if isinstance(body, dict) else body
        models: list[str] = []
        for item in items or []:
            model_id = item.get("id") if isinstance(item, dict) else item
            if isinstance(model_id, str) and model_id and model_id not in models:
                models.append(model_id)
        return models

    async def stream_text(
        self, messages: Sequence[dict[str, str]], *, task: str
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, stream=True)
        async for delta in self._stream(payload):
            yield delta

    async def _stream(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", self.endpoint, headers=self._headers(), json=payload
            ) as response:
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
                        self._capture_usage(event)
                    except json.JSONDecodeError as exc:
                        raise AIProviderError("Invalid Anthropic streaming response") from exc
                    event_type = event.get("type")
                    if event_type == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            text = delta.get("text")
                            if text:
                                yield text
                    elif event_type == "error":
                        raise AIProviderError(str(event.get("error") or event))

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(self.endpoint, headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise provider_error(response.status_code, response.text)
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise AIProviderError("Invalid Anthropic response") from exc
        if not isinstance(body, dict):
            raise AIProviderError("Anthropic response must be an object", category="invalid_response")
        self._capture_usage(body)
        return body

    async def structured(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        strict_schema = strict_json_schema(schema)
        tool = {
            "name": STRUCTURED_TOOL_NAME,
            "description": f"Return the {task} result as structured data.",
            "input_schema": strict_schema,
        }
        payload = self._payload(
            messages,
            stream=False,
            tools=[tool],
            tool_choice={"type": "tool", "name": STRUCTURED_TOOL_NAME},
        )
        try:
            body = await self._post(payload)
            result = self._tool_result(body)
            if result is not None and self._satisfies(result, strict_schema):
                return result
        except AIProviderError as exc:
            if exc.category in NON_RETRYABLE_CATEGORIES:
                raise
        # Tool forcing is unreliable on some Anthropic-compatible gateways
        # (missing required fields, or tools unsupported); ask for JSON text.
        return await self._structured_text(messages, strict_schema)

    @staticmethod
    def _tool_result(body: dict[str, Any]) -> dict[str, Any] | None:
        for block in body.get("content") or []:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and isinstance(block.get("input"), dict)
            ):
                return block["input"]
        return None

    @staticmethod
    def _satisfies(result: dict[str, Any], schema: dict[str, Any]) -> bool:
        required = schema.get("required")
        if not isinstance(required, list) or not required:
            return True
        return all(key in result for key in required)

    async def _structured_text(
        self, messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        fallback = list(messages)
        fallback.append(
            {
                "role": "system",
                "content": "Respond with a single JSON object only, no markdown, matching this schema:\n"
                + json.dumps(schema),
            }
        )
        body = await self._post(self._payload(fallback, stream=False))
        result = self._tool_result(body)
        if result is not None:
            return result
        text_parts: list[str] = []
        for block in body.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                text_parts.append(block["text"])
        if text_parts:
            return parse_json_text("".join(text_parts))
        raise AIProviderError("Provider returned no structured output", category="invalid_response")
