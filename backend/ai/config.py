import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str | None
    model: str


def load_provider_config() -> ProviderConfig | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return ProviderConfig(
        name="openai",
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key,
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )
