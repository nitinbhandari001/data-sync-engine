from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE = Path(__file__).parent.parent


class Settings(BaseSettings):
    database_url: str = "postgresql://dev:devpassword@localhost:5432/portfolio"
    groq_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    ai_provider: str = "groq"
    ai_fallback_enabled: bool = True
    default_conflict_strategy: str = "last_write_wins"
    sync_interval_minutes: int = 5
    mappings_dir: Path = _BASE / "config" / "mappings"
    data_dir: Path = _BASE / "data"
    slack_bot_token: str = ""
    slack_channel_sync: str = "#data-sync"
    log_level: str = "INFO"
    fastapi_port: int = 8009

    def has_llm(self) -> bool:
        return bool(self.groq_api_key or self.gemini_api_key or self.openrouter_api_key)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
