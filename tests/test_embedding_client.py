"""Worker HTTP contract checks without loading inference weights."""

from email import policy
from email.parser import BytesParser
from io import BytesIO
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


def request_body(request):
    if request.headers["content-type"].startswith("application/json"):
        return json.loads(request.content), {}
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + request.headers["content-type"] + "\r\n\r\n").encode()
        + request.content
    )
    fields = {
        part.get_param("name", header="content-disposition"): part
        for part in message.iter_parts()
    }
    body = json.loads(fields.pop("payload").get_payload(decode=True))
    return body, fields


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
        body, _ = request_body(request)
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


@pytest.mark.parametrize("api_key", [None, "client-key"])
def test_client_sends_configured_bearer_key(server, api_key):
    model = RemoteEmbeddingModel(
        Path("/unused"), transport=server.transport, api_key=api_key
    )
    try:
        model.embed_texts(["hello"])
        for request in server.calls:
            assert request.headers.get("Authorization") == (
                f"Bearer {api_key}" if api_key else None
            )
    finally:
        model.close()


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


def test_multipart_combined_frame_group(server, tmp_path):
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
        assert not [r for r in server.calls if r.url.path == "/v1/uploads"]
        requests = [r for r in server.calls if r.url.path == "/v1/embeddings"]
        assert len(requests) == 1
        body, files = request_body(requests[0])
        assert len(files) == 4
        parts = body["items"][0]["parts"]
        assert [p["type"] for p in parts] == ["text", "media", "media", "video_frames"]
        assert parts[0]["text"] == "Scene"
        assert len(parts[-1]["files"]) == 2
        assert len(set(parts[-1]["files"])) == 2
        assert files[parts[1]["file"]].get_payload(decode=True).startswith(b"\x89PNG")
        assert files[parts[2]["file"]].get_payload(decode=True).startswith(b"RIFF")
        assert files[parts[2]["file"]].get_content_type() == "audio/wav"
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
    worker = Worker(
        Settings(_env_file=None, embedding_api_keys=["worker-key", "rotation-key"]),
        None,
        None,
    )
    assert isinstance(worker._model(), Remote)
    assert worker._model() is worker._embedding_model
    assert len(calls) == 1
    assert calls[0]["base_url"] == "http://127.0.0.1:8001/"
    assert calls[0]["api_key"] == "worker-key"


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


def test_image_batches_have_request_local_file_references(server):
    model = client(server)
    images = [
        Image.new("RGB", (8, 8), color)
        for color in ["red", "blue", "green", "white", "black"]
    ]
    try:
        assert len(model.embed_images(images)) == 5
        requests = [r for r in server.calls if r.url.path == "/v1/embeddings"]
        assert len(requests) == 3
        seen = []
        for request in requests:
            body, files = request_body(request)
            assert len(files) == len(body["items"])
            assert {item["parts"][0]["file"] for item in body["items"]} == set(files)
            for item in body["items"]:
                data = files[item["parts"][0]["file"]].get_payload(decode=True)
                with Image.open(BytesIO(data)) as image:
                    seen.append(image.getpixel((0, 0)))
        assert seen == [image.getpixel((0, 0)) for image in images]
        assert not [r for r in server.calls if r.url.path == "/v1/uploads"]
    finally:
        model.close()


def test_video_multipart_preserves_frame_order(server):
    model = client(server)
    frames = [Image.new("RGB", (8, 8), color) for color in ["red", "blue", "red"]]
    try:
        model.embed_video(frames)
        body, files = request_body(server.calls[-1])
        references = body["items"][0]["parts"][0]["files"]
        pixels = []
        for reference in references:
            with Image.open(
                BytesIO(files[reference].get_payload(decode=True))
            ) as image:
                pixels.append(image.getpixel((0, 0)))
        assert pixels == [frame.getpixel((0, 0)) for frame in frames]
    finally:
        model.close()


def test_media_retry_resends_bytes_without_upload_ids(server):
    model = client(server)
    image = Image.new("RGB", (8, 8), "red")
    try:
        server.failure = 503
        with pytest.raises(EmbeddingError):
            model.embed_images([image])
        server.failure = None
        assert len(model.embed_images([image])) == 1
        requests = [r for r in server.calls if r.url.path == "/v1/embeddings"]
        assert len(requests) == 2
        first_body, first_files = request_body(requests[0])
        second_body, second_files = request_body(requests[1])
        assert first_body == second_body
        assert first_files["media_0"].get_payload(decode=True) == second_files[
            "media_0"
        ].get_payload(decode=True)
    finally:
        model.close()


def test_oversized_prepared_media_rejected_without_request(server):
    model = client(server)
    model.max_upload_bytes = 1
    try:
        with pytest.raises(EmbeddingInputError, match="upload limit"):
            model.embed_images([Image.new("RGB", (8, 8))])
        assert len(server.calls) == 2
    finally:
        model.close()


def test_request_byte_limit_splits_media_batch_without_reordering(server):
    model = client(server)
    image = Image.new("RGB", (8, 8), "red")
    prepared = model._image_file(image)
    first = [{"id": "0", "parts": [{"type": "media", "file": prepared}]}]
    request = model._client.build_request(
        "POST", "v1/embeddings", **model._request_inputs(first)
    )
    model.max_request_bytes = int(request.headers["content-length"])
    try:
        assert len(model.embed_images([image, image])) == 2
        requests = [
            request for request in server.calls if request.url.path == "/v1/embeddings"
        ]
        assert len(requests) == 2
        assert all(
            int(request.headers["content-length"]) <= model.max_request_bytes
            for request in requests
        )
        assert all(len(request_body(request)[0]["items"]) == 1 for request in requests)
    finally:
        model.close()


def test_single_item_request_limit_is_rejected_before_sending(server):
    model = client(server)
    model.max_request_bytes = 1
    try:
        with pytest.raises(EmbeddingInputError, match="request limit"):
            model.embed_images([Image.new("RGB", (8, 8), "red")])
        assert len(server.calls) == 2
    finally:
        model.close()


def test_file_count_limit_splits_video_batches(server, tmp_path):
    from search_anything.embeddings import MediaEmbeddingInput

    model = client(server)
    model.batch_size = 8
    model.max_video_frames = 32
    frame = tmp_path / "frame.png"
    Image.new("RGB", (8, 8), "red").save(frame)
    inputs = [MediaEmbeddingInput(frame_paths=(frame,) * 32) for _ in range(5)]
    try:
        assert len(model.embed_media_batch(inputs)) == 5
        requests = [
            request for request in server.calls if request.url.path == "/v1/embeddings"
        ]
        assert [len(request_body(request)[0]["items"]) for request in requests] == [
            4,
            1,
        ]
        assert [len(request_body(request)[1]) for request in requests] == [128, 32]
    finally:
        model.close()
