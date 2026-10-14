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
    ready_calls = []

    def mock_ready(url, api_key=None):
        ready_calls.append((url, api_key))
        return next(readiness)

    monkeypatch.setattr(manager, "ready", mock_ready)
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
    assert ready_calls == [
        ("http://127.0.0.1:8001/", "first-key"),
        ("http://127.0.0.1:8001/", "first-key"),
    ]


def test_ready_sends_authorization_header():
    import importlib.util
    from pathlib import Path
    import httpx

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "embedding_service_auth_ready_test", root / "scripts/embedding_service.py"
    )
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)

    def handle(request):
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/v1/models":
            auth = request.headers.get("Authorization")
            if auth != "Bearer secret-key":
                return httpx.Response(401, json={"detail": "Unauthorized"})
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": manager.MODEL_ID,
                            "revision": manager.MODEL_REVISION,
                            "output_dimensions": [manager.DIMENSIONS],
                            "test_mode": False,
                        }
                    ]
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handle)
    assert not manager.ready("http://127.0.0.1:8001", transport=transport)
    assert manager.ready(
        "http://127.0.0.1:8001", api_key="secret-key", transport=transport
    )
