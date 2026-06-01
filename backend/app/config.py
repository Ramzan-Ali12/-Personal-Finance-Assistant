"""Central application configuration.

All settings are read from environment variables (.env in development) so the
same image can run in any environment without code changes.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/finance"

    # Auth
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080

    # LLM (OpenAI-compatible)
    llm_provider: str = "openrouter"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_router_model: str = "anthropic/claude-3.5-haiku"
    llm_agent_model: str = "anthropic/claude-3.5-sonnet"
    llm_vision_model: str = "anthropic/claude-3.5-sonnet"

    # Embeddings
    embeddings_provider: str = "local"
    embeddings_base_url: str = "https://openrouter.ai/api/v1"
    embeddings_api_key: str = ""
    embeddings_model: str = "text-embedding-3-small"
    embeddings_dim: int = 384

    # Web search
    web_search_provider: str = "none"
    web_search_api_key: str = ""

    # CORS
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        """True when a real LLM endpoint is configured; otherwise mock mode."""
        return bool(self.llm_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
