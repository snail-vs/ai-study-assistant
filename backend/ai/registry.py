from .config import load_provider_config
from .providers.mock import MockTextProvider
from .providers.openai import OpenAIProvider
from .model_routing import resolve_model_route

PROVIDER_DEFAULTS = {
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
    "openrouter": ("https://openrouter.ai/api/v1", "openrouter/auto"),
    "opencode": ("https://opencode.ai/zen/v1", "deepseek-v4-pro"),
}

SUPPORTED_PROTOCOLS = {"openai_chat_completions", "openai_responses"}


def create_text_provider():
    config = load_provider_config()
    if config is None:
        return MockTextProvider()
    return OpenAIProvider(config.base_url, config.api_key or "", config.model)


def create_named_text_provider(name: str, api_key: str, model: str | None = None):
    if name not in PROVIDER_DEFAULTS:
        raise ValueError(f"Unsupported provider: {name}")
    base_url, default_model = PROVIDER_DEFAULTS[name]
    selected_model = model or default_model
    route = resolve_model_route(name, base_url, selected_model)
    if route.protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(
            f"Model {selected_model} uses unsupported protocol {route.protocol}; "
            "this protocol adapter has not been enabled yet"
        )
    return OpenAIProvider(
        base_url,
        api_key,
        selected_model,
        endpoint=route.endpoint,
        protocol=route.protocol,
    )
