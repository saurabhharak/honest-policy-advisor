"""Environment configuration."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


def _optional(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


@dataclass(frozen=True)
class Config:
    caspian_api_key: str
    caspian_base_url: str
    telegram_bot_token: str
    openai_api_key: str
    openai_base_url: str
    llm_model: str
    vision_model: str
    agent_username: str
    guardrails_enabled: bool
    guardrails_model: str
    opik_enabled: bool
    opik_url: str
    opik_api_key: str


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        llm_model = _optional("LLM_MODEL", "gpt-4o-mini")
        _config = Config(
            caspian_api_key=_require("CASPIAN_API_KEY"),
            caspian_base_url=_optional("CASPIAN_BASE_URL", "https://api.trycaspianai.com"),
            telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
            openai_api_key=_require("OPENAI_API_KEY"),
            openai_base_url=_optional("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            llm_model=llm_model,
            vision_model=_optional("VISION_MODEL", "Qwen/Qwen3-VL-8B-Instruct"),
            agent_username=_optional("AGENT_USERNAME", "policydecoder"),
            guardrails_enabled=os.getenv("GUARDRAILS_ENABLED", "").strip().lower()
            in ("1", "true", "yes"),
            guardrails_model=_optional("GUARDRAILS_MODEL", llm_model),
            opik_enabled=os.getenv("OPIK_ENABLED", "").strip().lower() in ("1", "true", "yes"),
            opik_url=_optional("OPIK_URL", ""),
            opik_api_key=_optional("OPIK_API_KEY", ""),
        )
    return _config
