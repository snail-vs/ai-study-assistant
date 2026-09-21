from collections.abc import Callable

from .config import load_provider_config
from .oauth_chatgpt import ChatGptCredential
from .providers.anthropic import AnthropicMessagesProvider
from .providers.chatgpt import DEFAULT_CODEX_MODEL, ChatGptCodexProvider
from .providers.mock import MockTextProvider
from .providers.openai import OpenAIProvider
from .model_routing import resolve_model_route
from .base import AICompatibilityError
from .capabilities import capabilities_for_route
from .model_catalog import ModelCatalogSpec

CHATGPT_PROVIDER = "chatgpt"

class ProviderDefinition:
    def __init__(
        self,
        base_url: str,
        default_model: str,
        *,
        model_catalog: ModelCatalogSpec | None = None,
    ) -> None:
        self.base_url = base_url
        self.default_model = default_model
        self.model_catalog = model_catalog


PROVIDER_DEFINITIONS = {
    # DeepSeek's current Responses API models. Keep the default aligned with
    # the provider catalog; legacy chat/reasoner IDs are no longer supported.
    "deepseek": ProviderDefinition("https://api.deepseek.com", "deepseek-flash"),
    # Gemini exposes an OpenAI-compatible endpoint.
    "google": ProviderDefinition(
        "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"
    ),
    "openrouter": ProviderDefinition("https://openrouter.ai/api/v1", "openrouter/auto"),
    "opencode": ProviderDefinition("https://opencode.ai/zen/v1", "deepseek-v4-pro"),
    # Anthropic Messages protocol (official API or compatible gateways).
    "anthropic": ProviderDefinition("https://api.anthropic.com", "claude-sonnet-5"),
    # Zhipu mainland and overseas accounts/keys are separate. Both expose the
    # OpenAI-compatible chat endpoint; no separate model catalog URL is assumed.
    "glm": ProviderDefinition("https://open.bigmodel.cn/api/paas/v4", "glm-5.2"),
    "zai": ProviderDefinition("https://api.z.ai/api/paas/v4", "glm-5.2"),
    # Subscription login: credentials come from the device-code OAuth flow.
    "chatgpt": ProviderDefinition("https://chatgpt.com/backend-api", DEFAULT_CODEX_MODEL),
}

# Kept as a small compatibility projection for callers that only need defaults.
PROVIDER_DEFAULTS = {
    name: (definition.base_url, definition.default_model)
    for name, definition in PROVIDER_DEFINITIONS.items()
}

SUPPORTED_PROTOCOLS = {"openai_chat_completions", "openai_responses", "anthropic_messages"}


def create_text_provider():
    config = load_provider_config()
    if config is None:
        return MockTextProvider()
    return OpenAIProvider(config.base_url, config.api_key or "", config.model)


def create_named_text_provider(
    name: str,
    api_key: str,
    model: str | None = None,
    *,
    oauth: ChatGptCredential | None = None,
    on_token_refresh: Callable[[ChatGptCredential], None] | None = None,
):
    if name == CHATGPT_PROVIDER:
        return ChatGptCodexProvider(model, oauth, on_token_refresh=on_token_refresh)
    if name not in PROVIDER_DEFAULTS:
        raise ValueError(f"Unsupported provider: {name}")
    definition = PROVIDER_DEFINITIONS[name]
    base_url = definition.base_url
    selected_model = model or definition.default_model
    try:
        route = resolve_model_route(name, base_url, selected_model)
    except ValueError as exc:
        raise AICompatibilityError(
            str(exc),
            category="unsupported_model",
        ) from exc
    if route.protocol not in SUPPORTED_PROTOCOLS:
        raise AICompatibilityError(
            f"Model {selected_model} uses unsupported protocol {route.protocol}; "
            "this protocol adapter has not been enabled yet",
            category="unsupported_protocol",
        )
    if route.protocol == "anthropic_messages":
        return AnthropicMessagesProvider(
            base_url,
            api_key,
            selected_model,
            endpoint=route.endpoint,
            protocol=route.protocol,
            route=route,
            capabilities=capabilities_for_route(route, name),
        )
    return OpenAIProvider(
        base_url,
        api_key,
        selected_model,
        endpoint=route.endpoint,
        protocol=route.protocol,
        route=route,
        capabilities=capabilities_for_route(route, name),
    )
