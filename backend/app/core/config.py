"""Application configuration.

All configuration comes from environment variables (optionally via a root
`.env` file). Nothing secret is ever hardcoded, and no secret is ever
returned by the health endpoints.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> root
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings.

    Reads the repository-root `.env` so a single file serves backend and tooling.
    """

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- application ----------
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    api_prefix: str = Field(default="/api")

    # ---------- database ----------
    # MongoDB Atlas in production; local mongod in development.
    mongodb_uri: str = Field(default="mongodb://localhost:27017")
    mongodb_db: str = Field(default="market_watchlist")
    # Accepted as an alias so a generic DATABASE_URL also works.
    database_url: str | None = Field(default=None)

    # ---------- auth ----------
    jwt_secret: str = Field(default="dev-only-insecure-secret-change-me-in-production-32b+")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=60 * 24 * 14)  # 14 days

    # ---------- CORS ----------
    cors_origins: str = Field(default="http://localhost:3000")

    # ---------- LLM (Groq) ----------
    # The user's .env may name this GROQ_API_KEY or simply GROQ; both are read.
    groq_api_key: str | None = Field(default=None)
    groq: str | None = Field(default=None)  # alias fallback
    groq_model: str = Field(default="openai/gpt-oss-120b")
    groq_timeout_seconds: float = Field(default=20.0)
    groq_max_retries: int = Field(default=2)
    groq_max_output_tokens: int = Field(default=700)

    # ---------- market data ----------
    demo_mode: bool = Field(default=False)
    market_provider_order: str = Field(default="yfinance,jugaad,demo")
    provider_timeout_seconds: float = Field(default=12.0)
    quote_cache_ttl_seconds: int = Field(default=60)
    history_cache_ttl_seconds: int = Field(default=60 * 60 * 6)
    news_cache_ttl_seconds: int = Field(default=60 * 10)

    # Two providers disagreeing by more than this fraction raises DATA_CONFLICT.
    price_conflict_tolerance_pct: float = Field(default=1.0)

    # Freshness thresholds (seconds) used to label observations.
    fresh_max_age_seconds: int = Field(default=120)
    delayed_max_age_seconds: int = Field(default=900)

    # ---------- optional Upstox (not required) ----------
    upstox_client_id: str | None = Field(default=None)
    upstox_client_secret: str | None = Field(default=None)
    upstox_redirect_uri: str | None = Field(default=None)
    upstox_access_token: str | None = Field(default=None)

    # ---------- change engine tuning ----------
    volume_noteworthy_multiple: float = Field(default=1.5)
    volume_significant_multiple: float = Field(default=2.0)
    volume_unusual_multiple: float = Field(default=3.0)

    @field_validator("demo_mode", mode="before")
    @classmethod
    def _parse_bool(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "on"}
        return v

    # ---------- derived ----------
    @property
    def resolved_mongo_uri(self) -> str:
        """Prefer an explicit Mongo URI, then a generic DATABASE_URL."""
        if self.mongodb_uri and self.mongodb_uri != "mongodb://localhost:27017":
            return self.mongodb_uri
        if self.database_url and self.database_url.startswith("mongodb"):
            return self.database_url
        return self.mongodb_uri

    @property
    def resolved_groq_key(self) -> str | None:
        """Accept GROQ_API_KEY (documented) or GROQ (shorthand)."""
        return self.groq_api_key or self.groq

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def provider_order(self) -> list[str]:
        return [p.strip().lower() for p in self.market_provider_order.split(",") if p.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
