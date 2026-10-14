"""Opt-in HTTP integration with a separate, real embedding service process."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import time
import wave

import httpx
import numpy as np
from PIL import Image
import pytest

from search_anything.embeddings import (
    MODEL_REVISION,
    ContextLimitError,
    LocalEmbeddingModel,
    MediaEmbeddingInput,
)
from search_anything.embedding_client import RemoteEmbeddingModel
from search_anything.ingestion import IngestionOptions, TextBlock
from search_anything.settings import Settings
from search_anything.worker import Worker

pytestmark = pytest.mark.skipif(
    os.environ.get("SEARCH_EMBEDDING_TESTS") != "1",
    reason="requires installed service environment and cached model",
)


@pytest.mark.asyncio
async def test_worker_against_real_http_embedding_service(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    service_dir = root / "embeddinggemma-api"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    settings = Settings(_env_file=None, embedding_backend="api", embedding_api_url=url)
    env = dict(
        os.environ,
        HOST="127.0.0.1",
        PORT=str(port),
        DEVICE="cpu",
        USE_FAKE_ADAPTER="false",
        MODEL_REVISION=MODEL_REVISION,
        MAX_CONTEXT_TOKENS="8192",
        MAX_BATCH_SIZE="8",
        VISION_MAX_SOFT_TOKENS="280",
        VIDEO_MAX_SOFT_TOKENS="140",
        TORCH_DTYPE="float32",
        UPLOAD_DIR=str(tmp_path / "uploads"),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
    )
    log_path = tmp_path / "service.log"
    with log_path.open("w") as log:
        service = subprocess.Popen(
            [
                str(service_dir / ".venv/bin/python"),
                "-m",
                "multimodal_embedding.server",
            ],
            cwd=service_dir,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    worker = Worker(settings, None, None)
    try:
        with httpx.Client(timeout=1, trust_env=False) as probe:
            for attempt in range(300):
                assert service.poll() is None, log_path.read_text()
                try:
                    if probe.get(url + "/health/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail(log_path.read_text())
        # A worker must never instantiate its local embedding model in API mode.
        import search_anything.worker as worker_module

        def forbidden(*args, **kwargs):
            raise AssertionError("worker loaded local embedding weights")

        monkeypatch.setattr(worker_module, "LocalEmbeddingModel", forbidden)
        local = LocalEmbeddingModel(settings.embedding_model_path, device="cpu")
        image = Image.new("RGB", (64, 64), "red")
        frames = [image, Image.new("RGB", (64, 64), "blue")]
        audio = tmp_path / "tone.wav"
        with wave.open(str(audio), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            tone = np.sin(np.arange(16000) * 2 * np.pi * 440 / 16000)
            output.writeframes((tone * 16000).astype("<i2").tobytes())
        document = "title: Report | text: Quarterly revenue increased."
        checks = [
            (
                worker._embed_text_batch,
                ([document, document + " Sales grew."],),
                {},
                local.embed_texts([document, document + " Sales grew."]),
            ),
            (
                worker._embed_query_text,
                ("city skyline",),
                {},
                local.embed_query("city skyline"),
            ),
            (worker._embed_image, (image,), {}, local.embed_images([image])[0]),
            (worker._embed_audio, (audio,), {}, local.embed_audio(audio)),
            (worker._embed_video, (frames,), {}, local.embed_video(frames)),
            (
                worker._embed_combined,
                ("A scene with sound",),
                {"image": image, "audio_path": audio, "video_frames": frames},
                local.embed_combined(
                    "A scene with sound",
                    image=image,
                    audio_path=audio,
                    video_frames=frames,
                ),
            ),
        ]
        for function, args, kwargs, expected in checks:
            actual = await worker.scheduler.submit(
                function, *args, kind="query", **kwargs
            )
            np.testing.assert_allclose(
                actual, expected, rtol=1e-4, atol=1e-5, err_msg=function.__name__
            )
        frame_paths = []
        for index, frame in enumerate(frames):
            path = tmp_path / f"frame-{index}.png"
            frame.save(path)
            frame_paths.append(path)
        media_inputs = [
            MediaEmbeddingInput(audio_path=audio),
            MediaEmbeddingInput(audio_path=audio),
            MediaEmbeddingInput(frame_paths=tuple(frame_paths)),
            MediaEmbeddingInput(frame_paths=tuple(reversed(frame_paths))),
            MediaEmbeddingInput(
                text="A scene with sound",
                audio_path=audio,
                frame_paths=tuple(frame_paths),
            ),
        ]
        expected_batch = [
            local.embed_audio(audio),
            local.embed_audio(audio),
            local.embed_video(frames),
            local.embed_video(list(reversed(frames))),
            local.embed_combined(
                "A scene with sound", audio_path=audio, video_frames=frames
            ),
        ]
        actual_batch = await worker._submit_media_batch(media_inputs, kind="ingestion")
        assert all(failure is None for _, failure in actual_batch)
        np.testing.assert_allclose(
            [vector for vector, _ in actual_batch], expected_batch, rtol=1e-4, atol=1e-5
        )
        np.testing.assert_allclose(
            local.embed_media_batch(media_inputs), expected_batch, rtol=1e-4, atol=1e-5
        )
        remote = worker._embedding_model
        assert isinstance(remote, RemoteEmbeddingModel)
        assert not hasattr(remote, "model")
        for text in ["", "Hello", document, "Café and 日本語.\nSecond line."]:
            assert remote.count_text_tokens(text) == local.count_text_tokens(text)
            assert remote.text_token_offsets(text) == local.text_token_offsets(text)
        source = "A sentence with useful content ends here. " * 100
        blocks = [
            TextBlock(
                source, None, {"offset_unit": "unicode_codepoint"}, 0, len(source)
            )
        ]
        chunks = await worker.scheduler.submit(
            worker._plan_chunks,
            blocks,
            "Report",
            IngestionOptions(text_chunk_tokens=64, text_overlap_tokens=8),
            kind="ingestion",
        )
        assert len(chunks) > 1
        assert all(chunk.token_count <= 64 for chunk in chunks)
        assert all(
            source[chunk.source_start : chunk.source_end] == chunk.text
            for chunk in chunks
        )
        with pytest.raises(ContextLimitError):
            remote.embed_texts(["word " * 9000])
        # Verify the service's processor rejection, bypassing the client's text precheck.
        with pytest.raises(ContextLimitError):
            remote._embed([[{"type": "text", "text": "word " * 9000}]])
    finally:
        await worker.scheduler.close()
        if isinstance(worker._embedding_model, RemoteEmbeddingModel):
            worker._embedding_model.close()
        service.terminate()
        try:
            service.wait(timeout=15)
        except subprocess.TimeoutExpired:
            service.kill()
            service.wait()


def test_managed_service_start_stop(tmp_path, monkeypatch):
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "embedding_service_manager", root / "scripts/embedding_service.py"
    )
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    monkeypatch.setattr(manager, "PID_FILE", tmp_path / "embedding.pid")
    monkeypatch.setattr(manager, "LOG_FILE", tmp_path / "embedding.log")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    settings = Settings(
        _env_file=None,
        embedding_api_url=f"http://127.0.0.1:{port}",
        embedding_device="cpu",
    )
    try:
        manager.start(settings)
        assert manager.ready(str(settings.embedding_api_url))
        assert manager.owned_pid() is not None
    finally:
        manager.stop()
    assert manager.owned_pid() is None
    assert not manager.PID_FILE.exists()
