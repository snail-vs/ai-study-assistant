import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from ..base import AIProviderError


class OpenAICompatibleProvider:
    """Chat Completions adapter for OpenAI and compatible endpoints."""

    def __init__(self, base_url: str, api_key: str, model: str, endpoint: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint or f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/models", headers=self._headers())
        if response.status_code >= 400:
            raise AIProviderError(f"{response.status_code}: {response.text}")
        try:
            return sorted(item["id"] for item in response.json()["data"] if item.get("id"))
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError("Invalid model list response from provider") from exc

    async def stream_text(
        self, messages: Sequence[dict[str, str]], *, task: str
    ) -> AsyncIterator[str]:
        payload = {"model": self.model, "messages": list(messages), "stream": True}
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", self.endpoint, headers=self._headers(), json=payload
            ) as response:
                if response.status_code >= 400:
                    raise AIProviderError(f"{response.status_code}: {await response.aread()}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {}).get("content")
                        if delta:
                            yield delta
                    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                        raise AIProviderError("Invalid streaming response from provider") from exc

    async def structured(
        self, messages: Sequence[dict[str, str]], *, task: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        is_deepseek = "deepseek" in self.base_url.lower()
        response_format = {"type": "json_object"} if is_deepseek else {
            "type": "json_schema",
            "json_schema": {"name": task, "schema": schema},
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
            if response.status_code == 400 and "response_format" in response.text:
                # Many compatible endpoints support JSON mode but not JSON Schema mode.
                payload["response_format"] = {"type": "json_object"}
                response = await client.post(
                    self.endpoint, headers=self._headers(), json=payload
                )
            if response.status_code == 400 and "response_format" in response.text:
                # Last compatibility fallback: the agent prompt still requires JSON.
                payload.pop("response_format", None)
                response = await client.post(
                    f"{self.base_url}/chat/completions", headers=self._headers(), json=payload
                )
        if response.status_code >= 400:
            raise AIProviderError(f"{response.status_code}: {response.text}")
        try:
            body = response.json()
            choices = body.get("choices")
            if not choices:
                raise AIProviderError("Provider returned no choices")
            content = choices[0]["message"]["content"]
            if isinstance(content, dict):
                return content
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(content)
        except AIProviderError:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError("Invalid structured response from provider") from exc
