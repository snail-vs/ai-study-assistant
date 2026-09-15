from .config import load_provider_config
from .providers.mock import MockTextProvider
from .providers.openai import OpenAIProvider


def create_text_provider():
    config = load_provider_config()
    if config is None:
        return MockTextProvider()
    return OpenAIProvider(config.base_url, config.api_key or "", config.model)
