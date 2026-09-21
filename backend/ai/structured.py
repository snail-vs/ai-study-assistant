"""Provider-neutral structured-output schema and error helpers."""

import json
import logging
from copy import deepcopy
from typing import Any

from .base import AIProviderError


logger = logging.getLogger("studycenter.ai.structured")


def strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize Pydantic output for strict JSON Schema implementations.

    Strict providers require every declared property to be required. Optional
    values should therefore be represented as nullable values, not omitted
    properties. Dynamic dictionaries are intentionally not rewritten here;
    business schemas should use a list of entries when cross-provider support
    is required.
    """
    result = deepcopy(schema)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object" and "properties" in value:
                value["additionalProperties"] = False
                value["required"] = list(value["properties"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result)
    return result


def classify_provider_error(status_code: int, body: str) -> tuple[str, str | None]:
    """Map unstable provider errors to stable categories and provider codes."""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = {}
    error = parsed.get("error", parsed) if isinstance(parsed, dict) else {}
    message = str(error.get("message", body)) if isinstance(error, dict) else body
    code = error.get("code") if isinstance(error, dict) else None
    lowered = f"{code or ''} {message}".lower()
    if status_code == 402 or "insufficient balance" in lowered or ("insufficient" in lowered and "credit" in lowered):
        return "insufficient_balance", code
    if status_code in (401, 403):
        return "authentication", code
    if status_code == 429:
        return "rate_limited", code
    if "invalid_json_schema" in lowered or "response_format" in lowered or ("schema" in lowered and "required" in lowered):
        return "schema_incompatible", code
    if status_code >= 500:
        return "provider_unavailable", code
    return "provider_error", code


def provider_error(status_code: int, body: str) -> AIProviderError:
    category, code = classify_provider_error(status_code, body)
    return AIProviderError(
        f"{status_code}: {body}",
        category=category,
        status_code=status_code,
        provider_code=code,
    )


def parse_json_text(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise AIProviderError("Provider returned non-text structured output", category="invalid_response")
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        if exc.msg != "Extra data":
            raise AIProviderError("Invalid structured response from provider", category="invalid_response") from exc
        try:
            value, end = json.JSONDecoder().raw_decode(content)
        except json.JSONDecodeError as recovery_exc:
            raise AIProviderError(
                "Invalid structured response from provider", category="invalid_response"
            ) from recovery_exc
        trailing = content[end:].strip()
        if not trailing:
            raise AIProviderError("Invalid structured response from provider", category="invalid_response") from exc
        logger.warning(
            "provider structured output contained trailing data; using first JSON object: trailing_chars=%s",
            len(trailing),
        )
    if not isinstance(value, dict):
        raise AIProviderError("Provider structured output must be an object", category="invalid_response")
    return value
