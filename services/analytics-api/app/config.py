from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    ENV: str = "dev"
    ANALYTICS_DB_URL: str | None = None
    ANALYTICS_CONTROL_DB_URL: str | None = None
    ANALYTICS_SEMANTIC_REGISTRY_PATH: str = str(
        Path(__file__).resolve().parent.parent / "semantic_registry"
    )
    DATABASE_URL: str | None = None
    ANALYTICS_QUERY_TIMEOUT: int = 10
    ANALYTICS_MAX_ROWS: int = 1_000
    ANALYTICS_DEMO_MODE: bool = False

    ANALYTICS_LLM_MODEL: str = "gpt-4o-mini"
    ANALYTICS_LLM_BASE_URL: str | None = None
    ANALYTICS_LLM_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    ANALYTICS_API_KEY: str | None = None
    ANALYTICS_CORS_ORIGINS: str = "http://localhost:5174"
    ANALYTICS_OPENSEARCH_URL: str | None = None
    ANALYTICS_CONTEXT_INDEX: str = "context-v1"
    ANALYTICS_DASHBOARDS_URL: str | None = None
    ANALYTICS_CONTEXT_BOOTSTRAP: bool = False

    @property
    def database_url(self) -> str | None:
        return self.ANALYTICS_DB_URL or self.DATABASE_URL

    @property
    def control_database_url(self) -> str | None:
        """Return the analytics-owned control-store URL, never a warehouse URL."""
        return self.ANALYTICS_CONTROL_DB_URL

    @property
    def semantic_registry_path(self) -> Path:
        return Path(self.ANALYTICS_SEMANTIC_REGISTRY_PATH)

    @property
    def llm_api_key(self) -> str | None:
        return self.ANALYTICS_LLM_API_KEY or self.OPENAI_API_KEY

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.ANALYTICS_CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def opensearch_url(self) -> str | None:
        return self.ANALYTICS_OPENSEARCH_URL

    @property
    def context_index(self) -> str:
        return self.ANALYTICS_CONTEXT_INDEX

    @property
    def dashboards_url(self) -> str | None:
        return self.ANALYTICS_DASHBOARDS_URL

    @property
    def context_bootstrap_enabled(self) -> bool:
        return self.ANALYTICS_CONTEXT_BOOTSTRAP


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
