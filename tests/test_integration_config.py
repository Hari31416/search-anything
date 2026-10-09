"""Reject unsafe integration targets before making any connection."""

import pytest

from integration_config import integration_settings


def test_integration_has_no_application_database_fallback(monkeypatch):
    monkeypatch.delenv("SEARCH_TEST_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="require explicit"):
        integration_settings()


@pytest.mark.parametrize(
    ("database", "endpoint", "bucket", "message"),
    [
        (
            "search",
            "http://localhost:9100",
            "search-anything-test-check",
            "separate database",
        ),
        (
            "search_test",
            "http://localhost:9000",
            "search-anything-test-check",
            "separate endpoint",
        ),
        (
            "search_test",
            "http://localhost:9100",
            "search-anything",
            "bucket must start",
        ),
    ],
)
def test_integration_rejects_live_targets(
    monkeypatch, database, endpoint, bucket, message
):
    monkeypatch.setenv(
        "SEARCH_DATABASE_URL",
        "postgresql+asyncpg://search:anything@localhost:55432/search",
    )
    monkeypatch.setenv("SEARCH_STORAGE_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv(
        "SEARCH_TEST_DATABASE_URL",
        f"postgresql+asyncpg://test:test@localhost:55433/{database}",
    )
    monkeypatch.setenv("SEARCH_TEST_STORAGE_ENDPOINT", endpoint)
    monkeypatch.setenv("SEARCH_TEST_STORAGE_BUCKET", bucket)
    with pytest.raises(ValueError, match=message):
        integration_settings()


def test_integration_accepts_explicit_test_targets(monkeypatch):
    monkeypatch.setenv(
        "SEARCH_TEST_DATABASE_URL",
        "postgresql+asyncpg://test:test@localhost:55433/search_test",
    )
    monkeypatch.setenv("SEARCH_TEST_STORAGE_ENDPOINT", "http://localhost:9100")
    monkeypatch.setenv("SEARCH_TEST_STORAGE_BUCKET", "search-anything-test-check")
    settings = integration_settings()
    assert settings.database_url.endswith("/search_test")
    assert settings.storage_bucket == "search-anything-test-check"
