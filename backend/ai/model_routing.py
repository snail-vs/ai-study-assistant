from dataclasses import dataclass


@dataclass(frozen=True)
class OriginProviderDefinition:
    id: str
    prefixes: tuple[str, ...]
    default_protocol: str


@dataclass(frozen=True)
class ModelRoute:
    access_provider: str
    origin_provider: str
    protocol: str
    endpoint: str


ORIGIN_PROVIDERS = (
    OriginProviderDefinition("openai", ("gpt-",), "openai_responses"),
    OriginProviderDefinition("anthropic", ("claude-",), "anthropic_messages"),
    OriginProviderDefinition("google", ("gemini-",), "openai_chat_completions"),
    OriginProviderDefinition("deepseek", ("deepseek-",), "openai_chat_completions"),
    OriginProviderDefinition("glm", ("glm-",), "openai_chat_completions"),
    OriginProviderDefinition("qwen", ("qwen-",), "openai_chat_completions"),
    OriginProviderDefinition("minimax", ("minimax-",), "openai_chat_completions"),
    OriginProviderDefinition("kimi", ("kimi-",), "openai_chat_completions"),
    OriginProviderDefinition("grok", ("grok-",), "openai_responses"),
    OriginProviderDefinition("muse", ("muse-spark-",), "openai_responses"),
    OriginProviderDefinition("mimo", ("mimo-",), "openai_chat_completions"),
    OriginProviderDefinition("ling", ("ling-",), "openai_chat_completions"),
    OriginProviderDefinition("nemotron", ("nemotron-",), "openai_chat_completions"),
    OriginProviderDefinition("big-pickle", ("big-pickle",), "openai_chat_completions"),
)

ORIGIN_BY_ID = {item.id: item for item in ORIGIN_PROVIDERS}

# An access provider can expose the same origin provider through another protocol.
# OpenCode's routes follow its published model/endpoint groups; they are grouped by
# origin provider instead of being repeated for every model ID.
ACCESS_ROUTES = {
    "opencode": {
        "openai": ("openai_responses", "/responses"),
        "anthropic": ("anthropic_messages", "/messages"),
        "google": ("google_generative", "/models"),
        "qwen": ("anthropic_messages", "/messages"),
        "deepseek": ("openai_chat_completions", "/chat/completions"),
        "glm": ("openai_chat_completions", "/chat/completions"),
        "minimax": ("openai_chat_completions", "/chat/completions"),
        "kimi": ("openai_chat_completions", "/chat/completions"),
        "grok": ("openai_responses", "/responses"),
        "muse": ("openai_responses", "/responses"),
        "mimo": ("openai_chat_completions", "/chat/completions"),
        "ling": ("openai_chat_completions", "/chat/completions"),
        "nemotron": ("openai_chat_completions", "/chat/completions"),
        "big-pickle": ("openai_chat_completions", "/chat/completions"),
    },
}

ACCESS_DEFAULTS = {
    "deepseek": ("deepseek", "openai_responses", "/responses"),
    "openrouter": (None, "openai_chat_completions", "/chat/completions"),
    "opencode": (None, None, None),
    "anthropic": ("anthropic", "anthropic_messages", "/v1/messages"),
}


def resolve_origin_provider(access_provider: str, model_id: str) -> str | None:
    """Resolve an origin provider from a namespace or stable model prefix."""
    namespace, _, model_name = model_id.partition("/")
    if namespace in ORIGIN_BY_ID:
        return namespace
    for definition in ORIGIN_PROVIDERS:
        if model_id.startswith(definition.prefixes) or model_name.startswith(definition.prefixes):
            return definition.id
    if access_provider in ORIGIN_BY_ID:
        return access_provider
    return None


def resolve_model_route(access_provider: str, base_url: str, model_id: str) -> ModelRoute:
    origin = resolve_origin_provider(access_provider, model_id)
    if origin is None:
        _, default_protocol, _ = ACCESS_DEFAULTS.get(access_provider, (None, None, None))
        if default_protocol:
            origin = access_provider
        else:
            raise ValueError(f"Cannot determine origin provider for model: {model_id}")
    route = ACCESS_ROUTES.get(access_provider, {}).get(origin)
    if route:
        protocol, path = route
    else:
        default_origin, default_protocol, default_path = ACCESS_DEFAULTS.get(
            access_provider, (access_provider, None, None)
        )
        protocol = default_protocol or ORIGIN_BY_ID[origin].default_protocol
        path = default_path or {
            "openai_responses": "/responses",
            "anthropic_messages": "/messages",
            "google_generative": f"/models/{model_id}",
            "openai_chat_completions": "/chat/completions",
        }[protocol]
        if default_origin and default_origin != origin:
            protocol = ORIGIN_BY_ID[origin].default_protocol
    endpoint = f"{base_url.rstrip('/')}{path}"
    if path == "/models":
        endpoint = f"{endpoint}/{model_id}"
    return ModelRoute(access_provider, origin, protocol, endpoint)
