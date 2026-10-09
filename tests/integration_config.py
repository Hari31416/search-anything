"""Opt-in integration tests must never inherit application service targets."""

import os
from uuid import uuid4

from sqlalchemy.engine import make_url

from search_anything.settings import Settings


def integration_settings() -> Settings:
    database_url = os.environ.get("SEARCH_TEST_DATABASE_URL")
    storage_endpoint = os.environ.get("SEARCH_TEST_STORAGE_ENDPOINT")
    storage_bucket = os.environ.get("SEARCH_TEST_STORAGE_BUCKET")
    if not all((database_url, storage_endpoint, storage_bucket)):
        raise ValueError(
            "Integration tests require explicit SEARCH_TEST_DATABASE_URL, "
            "SEARCH_TEST_STORAGE_ENDPOINT, and SEARCH_TEST_STORAGE_BUCKET. "
            "Application service targets are never used as defaults."
        )
    live = Settings()
    target = make_url(database_url)
    current = make_url(live.database_url)
    if (
        target.drivername != "postgresql+asyncpg"
        or not (target.database or "").endswith("_test")
        or target.database == current.database
    ):
        raise ValueError(
            "Integration database must be a separate database ending in _test"
        )
    if storage_endpoint.rstrip("/") == live.storage_endpoint.rstrip("/"):
        raise ValueError("Integration storage must use a separate endpoint")
    if not storage_bucket.startswith("search-anything-test-"):
        raise ValueError("Integration bucket must start with search-anything-test-")
    return Settings(
        _env_file=None,
        database_url=database_url,
        sync_database_url=target.set(drivername="postgresql+psycopg").render_as_string(
            hide_password=False
        ),
        storage_endpoint=storage_endpoint,
        storage_bucket=storage_bucket,
        storage_access_key=os.environ.get(
            "SEARCH_TEST_STORAGE_ACCESS_KEY", "search-test"
        ),
        storage_secret_key=os.environ.get(
            "SEARCH_TEST_STORAGE_SECRET_KEY", "testing-only"
        ),
        default_workspace_id=uuid4(),
        default_workspace_name="Integration",
    )
