"""Application settings loaded from environment variables."""

from functools import lru_cache
import os
from pathlib import Path
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from search_anything.devices import InferenceDevice


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
    embedding_model_path: Path = Path(
        "~/.cache/huggingface/hub/models--google--embeddinggemma-2/snapshots/"
        "914f7f89142e33e77833254d9c9b90c3cef7303b"
    ).expanduser()
    embedding_model_revision: str = "914f7f89142e33e77833254d9c9b90c3cef7303b"
    embedding_context_tokens: int = Field(default=8192, ge=256, le=8192)
    embedding_batch_size: int = Field(default=8, ge=1, le=32)
    embedding_device: InferenceDevice = "auto"
    chunk_target_tokens: int = Field(default=700, ge=64, le=4096)
    chunk_overlap_tokens: int = Field(default=80, ge=0, le=512)
    ocr_languages: str = "eng"
    whisper_checkpoint_path: Path = Path("~/.cache/whisper/tiny.pt").expanduser()
    whisper_model_name: str = "tiny"
    whisper_device: InferenceDevice = "auto"
    model_socket_path: Path = Path(f"/tmp/search-anything-{os.getuid()}/model.sock")

    @field_validator(
        "embedding_model_path",
        "whisper_checkpoint_path",
        "model_socket_path",
        mode="before",
    )
    @classmethod
    def expand_embedding_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser()


@lru_cache
def get_settings() -> Settings:
    return Settings()
