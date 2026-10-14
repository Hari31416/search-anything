"""Worker HTTP contract checks without loading inference weights."""

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
from PIL import Image
import pytest

from search_anything import embedding_client as module
from search_anything.embeddings import (
    DIMENSIONS,
    MODEL_ID,
    MODEL_REVISION,
    ContextLimitError,
    EmbeddingError,
)
from search_anything.embedding_client import (
    EmbeddingContractError,
    EmbeddingInputError,
    RemoteEmbeddingModel,
)
from search_anything.settings import Settings
from search_anything.worker import Worker


class Tokenizer:
    def __init__(self, *args):
        pass

    def count_text_tokens(self, text):
        return len(text.split()) + 2

    def text_token_offsets(self, text):
        return [(0, len(text))]


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(module, "LocalTextTokenizer", Tokenizer)
    state = SimpleNamespace(
        calls=[],
        failure=None,
        mutate=lambda data: None,
        metadata={
            "data": [
                {
                    "id": MODEL_ID,
                    "revision": MODEL_REVISION,
                    "output_dimensions": [768, 512, 256, 128],
                    "test_mode": False,
                    "configured_limits": {
                        "max_context_tokens": 8192,
                        "max_batch_size": 2,
                        "max_upload_bytes": 1024 * 1024,
                        "max_video_frames": 4,
                        "vision_max_soft_tokens": 280,
                        "video_max_soft_tokens": 140,
                    },
                }
            ]
        },
    )

    def handle(request):
        state.calls.append(request)
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json=state.metadata)
        if state.failure:
            return httpx.Response(state.failure, json={"error": {"code": "test_error"}})
        if request.url.path == "/v1/uploads":
            return httpx.Response(200, json={"upload_id": f"upload-{len(state.calls)}"})
        body = json.loads(request.content)
        vector = [1.0] + [0.0] * (DIMENSIONS - 1)
        data = {
            "model": MODEL_ID,
            "revision": MODEL_REVISION,
            "dimension": 768,
            "normalized": True,
            "embeddings": [
                {"id": item["id"], "embedding": vector, "dimension": 768}
                for item in body["items"]
            ],
        }
        state.mutate(data)
        return httpx.Response(200, json=data)

    state.transport = httpx.MockTransport(handle)
    return state


def client(server):
    return RemoteEmbeddingModel(Path("/unused"), transport=server.transport)


def test_text_batching_prompt_and_query_contract(server):
    model = client(server)
    try:
        texts = [f"title: Test | text: Document {i}" for i in range(5)]
        assert len(model.embed_texts(texts)) == 5
        assert len(model.embed_query("  city  ")) == 768
        bodies = [
            json.loads(r.content)
            for r in server.calls
            if r.url.path == "/v1/embeddings"
        ]
        assert [len(b["items"]) for b in bodies] == [2, 2, 1, 1]
        assert all(
            b["prompt_mode"] == "none" and b["truncate_dim"] == 768 for b in bodies
        )
        assert bodies[0]["items"][0]["parts"][0]["text"] == texts[0]
        assert (
            bodies[-1]["items"][0]["parts"][0]["text"]
            == "task: search result | query: city"
        )
        assert model.context_tokens == 8192
        assert model.count_text_tokens("hello") == 3
    finally:
        model.close()


@pytest.mark.parametrize("change", ["revision", "dimensions", "context", "visual"])
def test_incompatible_service_is_rejected_before_embedding(server, change):
    metadata = server.metadata["data"][0]
    if change == "revision":
        metadata["revision"] = "different"
    if change == "dimensions":
        metadata["output_dimensions"] = [256]
    if change == "context":
        metadata["configured_limits"]["max_context_tokens"] = 4096
    if change == "visual":
        metadata["configured_limits"]["video_max_soft_tokens"] = 70
    with pytest.raises(EmbeddingContractError):
        client(server)
    assert len(server.calls) == 2


@pytest.mark.parametrize(
    "status,exception",
    [
        (400, EmbeddingInputError),
        (413, ContextLimitError),
        (503, EmbeddingError),
        (500, EmbeddingError),
        (404, EmbeddingError),
    ],
)
def test_service_errors_preserve_retry_semantics(server, status, exception):
    model = client(server)
    server.failure = status
    try:
        with pytest.raises(exception):
            model.embed_query("hello")
    finally:
        model.close()


def test_timeout_is_retryable(server):
    model = client(server)

    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    model._client.close()
    model._client = httpx.Client(
        base_url="http://service/", transport=httpx.MockTransport(timeout)
    )
    try:
        with pytest.raises(EmbeddingError, match="ReadTimeout") as error:
            model.embed_query("hello")
        assert not isinstance(error.value, (EmbeddingInputError, ContextLimitError))
    finally:
        model.close()


@pytest.mark.parametrize(
    "change", ["revision", "shape", "nan", "zero", "missing", "order"]
)
def test_bad_vectors_never_reach_the_index(server, change):
    def mutate(data):
        if change == "revision":
            data["revision"] = "changed-after-startup"
        elif change == "shape":
            data["embeddings"][0]["embedding"] = [1.0]
        elif change == "nan":
            data["embeddings"][0]["embedding"][0] = "nan"
        elif change == "zero":
            data["embeddings"][0]["embedding"] = [0.0] * 768
        elif change == "missing":
            data["embeddings"].pop()
        elif change == "order":
            data["embeddings"].reverse()

    server.mutate = mutate
    model = client(server)
    try:
        with pytest.raises(EmbeddingContractError):
            model.embed_texts(["first", "second"])
    finally:
        model.close()


def test_media_uploads_and_combined_frame_group(server, tmp_path):
    import wave

    audio = tmp_path / "window.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 160)
    image = Image.new("RGB", (8, 8), "red")
    model = client(server)
    try:
        model.embed_combined(
            "Scene", image=image, audio_path=audio, video_frames=[image, image]
        )
        uploads = [r for r in server.calls if r.url.path == "/v1/uploads"]
        assert len(uploads) == 4
        assert b"image/png" in uploads[0].content and b"\x89PNG" in uploads[0].content
        assert b"audio/wav" in uploads[1].content and b"RIFF" in uploads[1].content
        body = json.loads(server.calls[-1].content)
        parts = body["items"][0]["parts"]
        assert [p["type"] for p in parts] == ["text", "media", "media", "video_frames"]
        assert parts[0]["text"] == "Scene"
        assert len(parts[-1]["upload_ids"]) == 2
        assert model.embed_images([]) == model.embed_texts([]) == []
        with pytest.raises(ContextLimitError):
            model.embed_video([image] * 5)
    finally:
        model.close()


def test_worker_defaults_to_api_without_loading_local_weights(monkeypatch):
    from search_anything import worker as module

    calls = []

    class Remote:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(module, "RemoteEmbeddingModel", Remote)

    def forbidden(*args, **kwargs):
        raise AssertionError("local model loaded")

    monkeypatch.setattr(module, "LocalEmbeddingModel", forbidden)
    worker = Worker(Settings(_env_file=None), None, None)
    assert isinstance(worker._model(), Remote)
    assert worker._model() is worker._embedding_model
    assert len(calls) == 1
    assert calls[0]["base_url"] == "http://127.0.0.1:8001/"


def test_local_backend_requires_explicit_selection(monkeypatch):
    from search_anything import worker as module

    marker = object()
    monkeypatch.setattr(module, "LocalEmbeddingModel", lambda *args, **kwargs: marker)
    worker = Worker(Settings(_env_file=None, embedding_backend="local"), None, None)
    assert worker._model() is marker


def test_fake_service_cannot_populate_real_index(server):
    server.metadata["data"][0]["test_mode"] = True
    with pytest.raises(EmbeddingContractError, match="test_mode"):
        client(server)
