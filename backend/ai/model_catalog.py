"""Provider model-list discovery with explicit fallback semantics."""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .base import AIProviderError
from .structured import provider_error


@dataclass(frozen=True)
class ModelCatalogSpec:
    """A provider-specific model catalog endpoint and its response format."""

    url: str
    parser: str = "openai_data"


@dataclass(frozen=True)
class ModelDiscovery:
    models: list[str]
    source: str
    warning: str | None = None
    key_validated: bool = False


def _model_ids(payload: Any, parser: str) -> list[str]:
    if parser != "openai_data":
        raise ValueError(f"Unsupported model catalog parser: {parser}")
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise AIProviderError("Invalid model list response from provider", category="invalid_response")
    return sorted(
        {
            item["id"]
            for item in payload["data"]
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
        }
    )


async def fetch_catalog(spec: ModelCatalogSpec, api_key: str) -> list[str]:
    """Fetch a documented provider-specific catalog endpoint."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                spec.url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise AIProviderError(
            f"Provider model catalog connection failed: {exc}", category="provider_unavailable"
        ) from exc
    if response.status_code >= 400:
        raise provider_error(response.status_code, response.text)
    try:
        return _model_ids(response.json(), spec.parser)
    except json.JSONDecodeError as exc:
        raise AIProviderError(
            "Invalid model list response from provider", category="invalid_response"
        ) from exc


def can_fall_back_to_manual(error: AIProviderError) -> bool:
    """Only catalog absence/shape failures may be hidden behind manual entry."""
    return error.status_code in (404, 405, 501) or error.category == "invalid_response"
