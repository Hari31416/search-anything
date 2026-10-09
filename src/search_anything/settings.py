"""Application settings loaded from environment variables."""

from functools import lru_cache
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEARCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://search:anything@localhost:55432/search"
    sync_database_url: str = (
        "postgresql+psycopg://search:anything@localhost:55432/search"
    )
    storage_endpoint: str = "http://localhost:9000"
    storage_region: str = "us-east-1"
    storage_access_key: str = "search-local"
    storage_secret_key: str = "search-local-secret"
    storage_bucket: str = "search-anything"
    storage_presign_seconds: int = Field(default=900, ge=60, le=604800)
    max_upload_bytes: int = Field(default=2 * 1024**3, ge=1024, le=20 * 1024**3)
    default_workspace_id: UUID = UUID("8d544a89-7b01-4de5-8df2-3af82c56e33e")
    default_workspace_name: str = "Local workspace"
    job_lease_seconds: int = Field(default=60, ge=5, le=3600)
    job_poll_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    job_max_attempts: int = Field(default=5, ge=1, le=20)


@lru_cache
def get_settings() -> Settings:
    return Settings()
