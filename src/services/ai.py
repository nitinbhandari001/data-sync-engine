"""Multi-provider LLM service (Groq → Gemini → OpenRouter cascade)."""
from __future__ import annotations
from dataclasses import dataclass
import structlog
from openai import AsyncOpenAI
from ..config import Settings

log = structlog.get_logger(__name__)


@dataclass
class LLMProvider:
    name: str
    api_key: str
    base_url: str
    model: str

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


class AIService:
    def __init__(self, providers: list[LLMProvider]) -> None:
        self._providers = [p for p in providers if p.is_configured]
        self._clients = [
            (p, AsyncOpenAI(api_key=p.api_key, base_url=p.base_url))
            for p in self._providers
        ]

    @classmethod
    def from_settings(cls, settings: Settings) -> AIService:
        return cls([
            LLMProvider("groq", settings.groq_api_key, "https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
            LLMProvider("gemini", settings.gemini_api_key, "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
            LLMProvider("openrouter", settings.openrouter_api_key, "https://openrouter.ai/api/v1", "meta-llama/llama-3.1-8b-instruct:free"),
        ])

    async def call_llm(self, system: str, user: str) -> str | None:
        for provider, client in self._clients:
            try:
                resp = await client.chat.completions.create(
                    model=provider.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    max_tokens=1024,
                )
                return resp.choices[0].message.content
            except Exception as exc:
                log.warning("llm_failed", provider=provider.name, error=str(exc))
        return None

    @property
    def has_providers(self) -> bool:
        return bool(self._providers)
