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
        self.capabilities = capabilities or capabilities_for_route(
            route or ModelRoute("unknown", "unknown", protocol, self.endpoint)
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/models", headers=self._headers())
        if response.status_code >= 400:
            raise provider_error(response.status_code, response.text)
        try:
            return sorted(item["id"] for item in response.json()["data"] if item.get("id"))
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
        response_format = {"type": "json_object"} if not self.capabilities.supports_json_schema else {
            "type": "json_schema",
            "json_schema": {"name": task, "schema": strict_json_schema(schema)},
        }
        payload = {
            "model": self.model,
            "messages": list(messages),
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
                    response = await client.post(self.endpoint, headers=self._headers(), json=payload)
                    if response.status_code >= 400 and provider_error(response.status_code, response.text).category == "schema_incompatible":
                        payload.pop("text", None)
                        response = await client.post(self.endpoint, headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise provider_error(response.status_code, response.text)
        try:
            body = response.json()
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
            return parse_json_text(content)
        except AIProviderError:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError("Invalid structured Responses response") from exc

    def _responses_payload(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": list(messages),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": task,
                    "schema": strict_json_schema(schema),
                    "strict": True,
                }
            },
        }
