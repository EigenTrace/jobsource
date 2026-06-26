"""Central configuration, loaded from environment / .env.

Every external key is optional. Helper flags (`has_deepseek`, etc.) let each
component decide whether to use the LLM/API path or fall back to heuristics.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv not installed yet — env vars still work
    pass


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # DeepSeek
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "").strip())
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip())
    deepseek_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip())

    # Apify
    apify_api_token: str = field(default_factory=lambda: os.getenv("APIFY_API_TOKEN", "").strip())
    apify_linkedin_actor: str = field(default_factory=lambda: os.getenv("APIFY_LINKEDIN_JOBS_ACTOR", "bebity~linkedin-jobs-scraper").strip())

    # Tavily
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", "").strip())

    # Tuning
    deep_resolve_top_n: int = field(default_factory=lambda: _as_int(os.getenv("DEEP_RESOLVE_TOP_N"), 3))
    browser_timeout_ms: int = field(default_factory=lambda: _as_int(os.getenv("BROWSER_TIMEOUT_MS"), 20000))
    browser_headless: bool = field(default_factory=lambda: _as_bool(os.getenv("BROWSER_HEADLESS"), True))

    @property
    def has_deepseek(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def has_apify(self) -> bool:
        return bool(self.apify_api_token)

    @property
    def has_tavily(self) -> bool:
        return bool(self.tavily_api_key)


settings = Settings()
