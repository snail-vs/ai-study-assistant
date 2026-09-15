from .config import load_provider_config
from .providers.mock import MockTextProvider
from .providers.openai import OpenAIProvider

PROVIDER_DEFAULTS = {
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
    "openrouter": ("https://openrouter.ai/api/v1", "openrouter/auto"),
    "opencode": ("https://opencode.ai/zen/v1", "deepseek-v4-pro"),
}


def create_text_provider():
    config = load_provider_config()
    if config is None:
        return MockTextProvider()
    return OpenAIProvider(config.base_url, config.api_key or "", config.model)


def create_named_text_provider(name: str, api_key: str):
    if name not in PROVIDER_DEFAULTS:
        raise ValueError(f"Unsupported provider: {name}")
    base_url, model = PROVIDER_DEFAULTS[name]
    return OpenAIProvider(base_url, api_key, model)
