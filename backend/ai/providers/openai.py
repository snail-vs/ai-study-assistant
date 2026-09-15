from .openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    """Named adapter kept separate so provider-specific behavior can evolve later."""
