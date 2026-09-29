"""
Application configuration using Pydantic Settings.

Source: Based on IDENTITY_AND_TENANCY.md, SECURITY.md
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo-root .env is found from any working directory; a .env in the current directory
# (listed last) overrides it. Real environment variables override both.
_ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(str(_ROOT_ENV), ".env"),
        env_file_encoding="utf-8-sig",  # tolerate the BOM Windows editors add
        extra="ignore",
    )

    # === Application ===
    app_name: str = "supragents"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # === Database ===
    database_url: str = "postgresql+asyncpg://supragents:supragents@localhost:5432/supragents"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_echo: bool = False

    # === Redis ===
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50

    # === Security ===
    jwt_secret_key: str = "change-me-in-production-use-env-var"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # === LLM Providers ===
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    default_llm_provider: str = "openai"
    default_llm_model: str = "gpt-4o"
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 2

    # === Kernel Policy ===
    max_retry_attempts: int = 2         # W=2 for all mutation types
    default_timeout_seconds: float = 300.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery_seconds: int = 60
    max_delegation_depth: int = 3
    max_concurrent_executions_per_tenant: int = 100

    # === Observability ===
    otel_exporter_endpoint: str = "http://localhost:4317"
    enable_metrics: bool = True
    enable_tracing: bool = True
    enable_audit_log: bool = True

    # === Worker ===
    worker_endpoint: str = "http://localhost:8080"
    worker_heartbeat_interval_seconds: int = 30
    worker_heartbeat_timeout_seconds: int = 90
    worker_max_concurrent: int = 10

    # === Memory ===
    memory_backend: str = "postgres"     # postgres, lancedb, memory
    lance_db_path: str = "./data/lancedb"

    # === Secrets ===
    deepseek_api_key: str = ""

    # === HTTP ===
    cors_origins: str = ""  # comma-separated allowed origins; empty = no CORS

    # === Feature Flags ===
    feature_kill_switch: bool = True
    feature_mutation_safety: bool = True
    feature_tenant_isolation: bool = True
    feature_audit_log: bool = True
    feature_event_replay: bool = True
    feature_progressive_verification: bool = True


SETTINGS = Settings()


def get_settings():
    """Return the settings singleton. Used by app.py for dependency injection."""
    return SETTINGS
