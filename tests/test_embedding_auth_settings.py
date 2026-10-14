import pytest
from pydantic import ValidationError

from search_anything.settings import Settings


@pytest.mark.parametrize("value", ["", "[]", "  ", '["first-key","second-key"]'])
def test_embedding_keys_from_environment(monkeypatch, value):
    monkeypatch.setenv("SEARCH_EMBEDDING_API_KEYS", value)
    cfg = Settings(_env_file=None)
    expected = ["first-key", "second-key"] if "first-key" in value else []
    assert [key.get_secret_value() for key in cfg.embedding_api_keys] == expected
    assert "first-key" not in repr(cfg)


@pytest.mark.parametrize("value", ['[""]', '["   "]', '"key"', "not-json"])
def test_invalid_embedding_keys_fail(monkeypatch, value):
    monkeypatch.setenv("SEARCH_EMBEDDING_API_KEYS", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_launcher_forwards_keys_to_local_service(monkeypatch, tmp_path):
    import importlib.util
    import json
    from pathlib import Path
    from types import SimpleNamespace

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "embedding_service_auth_test", root / "scripts/embedding_service.py"
    )
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    monkeypatch.setattr(manager, "PID_FILE", tmp_path / "embedding.pid")
    monkeypatch.setattr(manager, "LOG_FILE", tmp_path / "embedding.log")
    monkeypatch.setattr(manager, "owned_pid", lambda: None)
    readiness = iter([False, True])
    monkeypatch.setattr(manager, "ready", lambda url: next(readiness))
    launches = []

    def launch(*args, **kwargs):
        launches.append(kwargs)
        return SimpleNamespace(pid=123, poll=lambda: None)

    monkeypatch.setattr(manager.subprocess, "Popen", launch)
    manager.start(
        Settings(_env_file=None, embedding_api_keys=["first-key", "second-key"])
    )
    assert json.loads(launches[0]["env"]["SEARCH_EMBEDDING_API_KEYS"]) == [
        "first-key",
        "second-key",
    ]
