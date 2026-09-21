import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from ..base import AIProviderError
from ..capabilities import ModelCapabilities, capabilities_for_route
from ..model_routing import ModelRoute
from ..structured import parse_json_text, provider_error, strict_json_schema


class OpenAICompatibleProvider:
    """Provider adapter for Chat Completions and OpenAI Responses endpoints."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        endpoint: str | None = None,
        protocol: str = "openai_chat_completions",
        capabilities: ModelCapabilities | None = None,
        route: ModelRoute | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.protocol = protocol
        self.endpoint = endpoint or f"{self.base_url}/chat/completions"
        self.access_provider = route.access_provider if route else None
        self.capabilities = capabilities or capabilities_for_route(
            route or ModelRoute("unknown", "unknown", protocol, self.endpoint)
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _json_object_messages(
        messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> list[dict[str, str]]:
        """Expose the output contract when an endpoint only supports JSON mode.

        JSON-object mode guarantees syntactically valid JSON, but it does not
        communicate which fields the object must contain. Supplying the schema
        in-band keeps such providers aligned with providers that enforce JSON
        Schema server-side.
        """
        return [
            *messages,
            {
                "role": "system",
                "content": (
                    "只返回一个 JSON 对象，不要 Markdown 或解释。输出必须符合以下 JSON Schema，"
                    "包含所有 required 字段并满足数组长度等约束：\n"
                    + json.dumps(schema, ensure_ascii=False)
                ),
            },
        ]

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise AIProviderError(
                f"Provider model list connection failed: {exc}", category="provider_unavailable"
            ) from exc
        if response.status_code >= 400:
            raise provider_error(response.status_code, response.text)
        try:
            models = sorted(item["id"] for item in response.json()["data"] if item.get("id"))
            if not models:
                raise AIProviderError("Provider returned an empty model list", category="invalid_response")
            return models
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError("Invalid model list response from provider") from exc

    async def stream_text(
        self, messages: Sequence[dict[str, str]], *, task: str
    ) -> AsyncIterator[str]:
        if self.protocol == "openai_responses":
            async for delta in self._stream_responses(messages):
                yield delta
            return
        payload = {"model": self.model, "messages": list(messages), "stream": True}
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
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        # Compatible providers may send usage/final chunks with an
                        # empty choices array. They are valid SSE events, but do
                        # not contain text to yield.
                        choices = chunk.get("choices")
                        if not choices:
                            if chunk.get("error"):
                                raise AIProviderError(str(chunk["error"]))
                            continue
                        choice = choices[0]
                        delta = choice.get("delta", {}).get("content")
                        if delta:
                            yield delta
                    except AIProviderError:
                        raise
                    except (AttributeError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                        raise AIProviderError("Invalid streaming response from provider") from exc

    async def _stream_responses(self, messages: Sequence[dict[str, str]]) -> AsyncIterator[str]:
        payload = {"model": self.model, "input": list(messages), "stream": True}
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
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise AIProviderError("Invalid Responses streaming response") from exc
                    if event.get("type") == "response.output_text.delta":
                        delta = event.get("delta")
                        if delta:
                            yield delta
                    elif event.get("type") == "error" or event.get("error"):
                        raise AIProviderError(str(event.get("error") or event))

    async def structured(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        if self.protocol == "openai_responses":
            return await self._structured_responses(messages, task=task, schema=schema)
        json_mode_messages = self._json_object_messages(messages, schema)
        response_format = {"type": "json_object"} if not self.capabilities.supports_json_schema else {
            "type": "json_schema",
            "json_schema": {"name": task, "schema": strict_json_schema(schema)},
        }
        payload = {
            "model": self.model,
            "messages": list(messages) if self.capabilities.supports_json_schema else json_mode_messages,
            "temperature": 0.2,
            "response_format": response_format,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                self.endpoint, headers=self._headers(), json=payload
            )
            if response.status_code >= 400 and provider_error(response.status_code, response.text).category == "schema_incompatible":
                # Many compatible endpoints support JSON mode but not JSON Schema mode.
                payload["response_format"] = {"type": "json_object"}
                payload["messages"] = json_mode_messages
                response = await client.post(
                    self.endpoint, headers=self._headers(), json=payload
                )
            if response.status_code >= 400 and provider_error(response.status_code, response.text).category == "schema_incompatible":
                # Last compatibility fallback: the agent prompt still requires JSON.
                payload.pop("response_format", None)
                response = await client.post(
                    f"{self.base_url}/chat/completions", headers=self._headers(), json=payload
                )
        if response.status_code >= 400:
            raise provider_error(response.status_code, response.text)
        try:
            body = response.json()
            choices = body.get("choices")
            if not choices:
                raise AIProviderError("Provider returned no choices")
            return parse_json_text(choices[0]["message"]["content"])
        except AIProviderError:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError("Invalid structured response from provider") from exc

    async def _structured_responses(
        self,
        messages: Sequence[dict[str, str]],
        *,
        task: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._responses_payload(messages, task=task, schema=schema)
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(self.endpoint, headers=self._headers(), json=payload)
            if response.status_code >= 400:
                error = provider_error(response.status_code, response.text)
                if error.category == "schema_incompatible" and self.capabilities.supports_json_object:
                    payload["text"]["format"] = {"type": "json_object"}
                    payload["input"] = self._json_object_messages(messages, schema)
                    response = await client.post(self.endpoint, headers=self._headers(), json=payload)
                    if response.status_code >= 400 and provider_error(response.status_code, response.text).category == "schema_incompatible":
                        payload.pop("text", None)
                        response = await client.post(self.endpoint, headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise provider_error(response.status_code, response.text)
        try:
            body = response.json()
            return parse_json_text(self._responses_content(body))
        except AIProviderError:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError("Invalid structured Responses response") from exc

    @staticmethod
    def _responses_content(body: dict[str, Any]) -> str:
        """Extract completed Responses text and reject incomplete generations."""
        status = body.get("status")
        if status in {"incomplete", "failed"}:
            detail = body.get("incomplete_details") or body.get("error") or {}
            if isinstance(detail, dict):
                reason = detail.get("reason") or detail.get("message")
            else:
                reason = str(detail)
            raise AIProviderError(
                f"Responses generation {status}: {reason or 'no detail'}",
                category="invalid_response",
            )
        content = body.get("output_text")
        if not content:
            for output in body.get("output", []):
                for item in output.get("content", []):
                    if item.get("type") in ("output_text", "text") and item.get("text"):
                        content = item["text"]
                        break
                if content:
                    break
        if not isinstance(content, str):
            raise AIProviderError("Provider returned no Responses output text")
        return content

    def _responses_payload(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        text_format: dict[str, Any] = {
            "type": "json_schema",
            "name": task,
            "schema": strict_json_schema(schema),
        }
        if self.capabilities.strict_json_schema:
            text_format["strict"] = True
        payload = {
            "model": self.model,
            "input": list(messages),
            "text": {"format": text_format},
        }
        # DeepSeek Responses enables thinking by default. For schema-bound
        # output this can leak a second JSON object into output_text, which is
        # not parseable as one structured response.
        if self.access_provider == "deepseek":
            payload["reasoning"] = {"effort": "none"}
        return payload
