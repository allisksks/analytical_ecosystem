"""Application settings loaded from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- general ---
    env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "Analytics Platform"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_json: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- storage of platform metadata ---
    database_url: str = "postgresql+asyncpg://platform:platform@localhost:5432/platform"
    redis_url: str | None = "redis://localhost:6379/0"

    # --- security ---
    secret_key: SecretStr = SecretStr("change-me-in-production-please-32b")
    # Key used to encrypt connector credentials at rest (Fernet-compatible, urlsafe base64, 32 bytes).
    # When empty a key is derived from secret_key (fine for dev, NOT for prod).
    encryption_key: SecretStr | None = None
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 14
    auth_mode: Literal["local", "oidc"] = "local"
    mfa_required_for_admins: bool = True
    cookie_secure: bool = True
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    # --- first start ---
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: SecretStr | None = None
    bootstrap_demo: bool = False
    # password for demo users of every role (only when bootstrap_demo is on)
    bootstrap_demo_password: SecretStr = SecretStr("demo-pass-2026")
    clickhouse_demo_url: str | None = None

    # --- query service ---
    query_default_limit: int = 10_000
    query_max_limit: int = 100_000
    query_timeout_s: int = 60
    query_cache_ttl_s: int = 900
    source_max_concurrency: int = 4

    # --- demo data ---
    demo_data_dir: str = "./demo-data"

    # --- AI gateway (OpenAI-compatible API: vLLM / Ollama / Yandex AI Studio) ---
    ai_enabled: bool = False
    ai_base_url: str = "http://localhost:11434/v1"
    ai_api_key: SecretStr | None = None
    ai_chat_model: str = "qwen3:8b"
    ai_sql_model: str | None = None
    ai_embedding_model: str | None = None
    ai_timeout_s: int = 120
    # Some providers (Yandex AI Studio) need a project/folder header.
    ai_project_header: str | None = None
    ai_project_id: str | None = None
    # Guard: cloud providers are allowed only for demo data (see TZ section 10).
    ai_allow_cloud: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
