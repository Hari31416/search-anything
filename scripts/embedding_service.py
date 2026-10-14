"""Manage only the embedding service process started by this checkout."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from urllib.parse import urlsplit

import httpx

from search_anything.embeddings import DIMENSIONS, MODEL_ID, MODEL_REVISION
from search_anything.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "logs/embedding.pid"
LOG_FILE = ROOT / "logs/embedding.log"


def ready(url: str) -> bool:
    try:
        with httpx.Client(timeout=2, trust_env=False) as client:
            response = client.get(url.rstrip("/") + "/health/ready")
            response.raise_for_status()
            if response.json().get("status") != "ready":
                return False
            response = client.get(url.rstrip("/") + "/v1/models")
            response.raise_for_status()
            return any(
                model.get("test_mode") is False
                and model.get("id") == MODEL_ID
                and model.get("revision") == MODEL_REVISION
                and DIMENSIONS in model.get("output_dimensions", [])
                for model in response.json().get("data", [])
            )
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        return False


def owned_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text())
        if pid <= 1:
            return None
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return pid if "multimodal_embedding.server" in command else None
    except (OSError, ValueError):
        return None


def start(settings: Settings) -> None:
    if settings.embedding_backend != "api":
        print("Embedding backend is local; standalone service not started.")
        return
    url = str(settings.embedding_api_url)
    parsed = urlsplit(url)
    if ready(url):
        print(f"Embedding service ready at {url}")
        return
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.scheme != "http"
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeError(
            "Configured embedding service is unavailable. Start the remote service before the worker."
        )
    if owned_pid() is not None:
        raise RuntimeError(
            f"Embedding service is already starting or unhealthy. See {LOG_FILE}"
        )
    python = ROOT / "embeddinggemma-api/.venv/bin/python"
    if not python.exists():
        raise RuntimeError(
            "Embedding service environment is missing. Run make setup-embedding."
        )
    LOG_FILE.parent.mkdir(exist_ok=True)
    env = dict(
        os.environ,
        HOST=parsed.hostname,
        PORT=str(parsed.port or 80),
        SEARCH_EMBEDDING_API_KEYS=json.dumps(
            [key.get_secret_value() for key in settings.embedding_api_keys]
        ),
        DEVICE=settings.embedding_device,
        MODEL_ID=MODEL_ID,
        MODEL_REVISION=settings.embedding_model_revision,
        MAX_CONTEXT_TOKENS=str(settings.embedding_context_tokens),
        MAX_BATCH_SIZE=str(settings.embedding_batch_size),
        VISION_MAX_SOFT_TOKENS="280",
        VIDEO_MAX_SOFT_TOKENS="140",
        TORCH_DTYPE="float32",
        USE_FAKE_ADAPTER="false",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        PYTHONUNBUFFERED="1",
    )
    with LOG_FILE.open("ab") as log:
        process = subprocess.Popen(
            [str(python), "-m", "multimodal_embedding.server"],
            cwd=ROOT / "embeddinggemma-api",
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_FILE.write_text(str(process.pid))
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Embedding service exited. See {LOG_FILE}")
            if ready(url):
                print(f"Embedding service started at {url}; logs: {LOG_FILE}")
                return
            time.sleep(0.25)
        raise RuntimeError(
            f"Embedding service did not become ready within 90 seconds. See {LOG_FILE}"
        )
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        PID_FILE.unlink(missing_ok=True)
        raise


def stop() -> None:
    pid = owned_pid()
    if pid is None:
        PID_FILE.unlink(missing_ok=True)
        print("No embedding service managed by this checkout is running.")
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 15
    while owned_pid() is not None and time.monotonic() < deadline:
        time.sleep(0.1)
    if owned_pid() is not None:
        raise RuntimeError(
            "Embedding service is still shutting down; retry stop after active inference completes."
        )
    PID_FILE.unlink(missing_ok=True)
    print("Embedding service stopped.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"])
    action = parser.parse_args().action
    settings = Settings()
    if action == "start":
        start(settings)
    elif action == "stop":
        stop()
    elif settings.embedding_backend != "api":
        print("Embedding backend: local")
    else:
        print(
            f'Embedding service: {"ready" if ready(str(settings.embedding_api_url)) else "unavailable"} at {settings.embedding_api_url}'
        )


if __name__ == "__main__":
    main()
