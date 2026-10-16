"""Application settings, loaded from environment variables (and an optional .env file).

Every secret comes from the environment. Nothing sensitive is hard-coded except
clearly-labelled *development* defaults that the app refuses to use in production.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEV_SECRET = "dev-only-insecure-secret-change-me-0123456789abcdef"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- general ---
    app_name: str = "PhishGuard"
    environment: str = "development"  # development | test | production
    log_level: str = "INFO"

    # --- database ---
    # Default is a zero-setup SQLite file. Set DATABASE_URL to a postgresql+psycopg:// URL for Postgres.
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'phishguard.db').as_posix()}"

    # --- auth ---
    jwt_secret: str = DEV_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False  # set true behind HTTPS
    cookie_samesite: str = "lax"
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # --- web ---
    frontend_origin: str = "http://localhost:3000"
    max_request_bytes: int = 256_000  # hard cap on request bodies

    # --- rate limits (requests per minute per client) ---
    rate_limit_auth: int = 10
    rate_limit_ai: int = 30
    rate_limit_report: int = 20

    # --- AI ---
    ai_provider: str = "demo"  # demo | openai | anthropic
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5"
    ai_timeout_seconds: float = 30.0
    chroma_path: str = str(BACKEND_DIR / ".chroma")
    vector_store: str = "auto"  # auto | chroma | memory

    # --- optional infrastructure ---
    redis_url: str | None = None  # feature flag: when set, cache uses Redis
    oidc_mock_enabled: bool = True  # documented mock IdP for SSO-readiness demos

    @field_validator("jwt_secret")
    @classmethod
    def _secret_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def demo_mode(self) -> bool:
        """True when no real AI provider is configured -> outputs are labelled DEMO."""
        if self.ai_provider == "openai" and self.openai_api_key:
            return False
        if self.ai_provider == "anthropic" and self.anthropic_api_key:
            return False
        return True

    def check_production_safety(self) -> None:
        if self.environment == "production":
            if self.jwt_secret == DEV_SECRET:
                raise RuntimeError("Refusing to start in production with the development JWT secret")
            if not self.cookie_secure:
                raise RuntimeError("COOKIE_SECURE must be true in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
