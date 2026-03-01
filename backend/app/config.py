"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    HERMES = "hermes"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Settings(BaseSettings):
    """All application settings, loaded from .env / environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Model Provider ---
    model_provider: ModelProvider = ModelProvider.OPENAI
    model_name: str = "gpt-4o"
    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: str = "sk-your-api-key-here"

    # --- Agent Configuration ---
    max_iterations: int = 15
    context_compression_threshold_tokens: int = 8000
    agent_temperature: float = 0.1

    # --- Workspace Security ---
    workspace_root: Path = Path("/workspace")

    # --- Risk Approval ---
    auto_approve_risk_level: RiskLevel = RiskLevel.LOW

    # --- Database ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "codesentry"
    postgres_password: str = "codesentry_dev"
    postgres_db: str = "codesentry"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # --- ChromaDB ---
    chroma_host: str = "chromadb"
    chroma_port: int = 8000

    # --- Redis ---
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""

    @property
    def redis_dsn(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    # --- Prompt Cache ---
    prompt_cache_enabled: bool = True
    prompt_cache_ttl_seconds: int = 3600

    # --- Audit ---
    audit_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- Server ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- Frontend ---
    vite_api_base_url: str = "http://localhost:8000"


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the cached Settings singleton, creating it on first call."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
