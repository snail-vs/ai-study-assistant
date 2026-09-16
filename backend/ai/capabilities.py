"""Protocol and model capability profiles used by the AI gateway."""

from dataclasses import dataclass

from .model_routing import ModelRoute


@dataclass(frozen=True)
class ModelCapabilities:
    protocol: str
    supports_streaming: bool = True
    supports_json_schema: bool = False
    supports_json_object: bool = False
    strict_json_schema: bool = False


def capabilities_for_route(route: ModelRoute, access_provider: str | None = None) -> ModelCapabilities:
    """Return conservative defaults for a resolved protocol.

    Providers can still downgrade at runtime because advertised protocol
    support is not consistent across compatible gateways and model families.
    """
    if route.protocol == "openai_responses":
        return ModelCapabilities(
            protocol=route.protocol,
            supports_json_schema=True,
            supports_json_object=True,
            strict_json_schema=True,
        )
    if route.protocol == "openai_chat_completions":
        if access_provider == "deepseek":
            return ModelCapabilities(
                protocol=route.protocol,
                supports_json_object=True,
            )
        return ModelCapabilities(
            protocol=route.protocol,
            supports_json_schema=True,
            supports_json_object=True,
        )
    if route.protocol == "anthropic_messages":
        return ModelCapabilities(protocol=route.protocol, supports_json_object=True)
    return ModelCapabilities(protocol=route.protocol)
