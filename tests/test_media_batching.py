"""Media batching keeps chunk alignment, bounded queues, and temporary files."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from search_anything import worker as module
from search_anything.embeddings import ContextLimitError, MediaEmbeddingInput
from search_anything.ingestion import IngestionOptions
from search_anything.media import DecodedFrames, MediaProbe, MediaWindow
from search_anything.worker import Worker


@pytest.fixture
def prepared_worker(monkeypatch):
    worker = Worker.__new__(Worker)
    worker.settings = SimpleNamespace(
        embedding_batch_size=4, whisper_model_name="tiny", ocr_languages="eng"
    )
    batches = []
    paths = []

    def extract_audio(source, path, window):
        path.write_text(str(window.start))
        paths.append(path)

    def extract_frames(source, directory, window, fps):
        directory.mkdir()
        path = directory / "frame.png"
        Image.new("RGB", (8, 8), "red").save(path)
        paths.append(path)
        return DecodedFrames([path], [window.start], fps)

    class Scheduler:
        async def submit(self, function, *args, **kwargs):
            if function.__name__ == "_transcribe":
                start = args[0].read_text()
                return {
                    "language": "en",
                    "segments": [{"text": f"Window {start}", "start": 0, "end": 1}],
                }
            assert function.__name__ == "_embed_media_batch"
            assert kwargs["kind"] in {"query", "ingestion"}
            batch = args[0]
            assert 0 < len(batch) <= 4
            assert all(path.exists() for item in batch for path in item.paths)
            batches.append((kwargs["kind"], list(batch)))
            if kwargs["kind"] == "query":
                return [
                    ([1.0, 0.0] if item.audio_path else [0.0, 1.0], None)
                    for item in batch
                ]
            return [
                (
                    [
                        float(item.audio_path.read_text()) if item.audio_path else -1,
                        float(bool(item.text)),
                    ],
                    None,
                )
                for item in batch
            ]

    worker.scheduler = Scheduler()
    monkeypatch.setattr(module, "extract_audio_window", extract_audio)
    monkeypatch.setattr(module, "extract_video_frames", extract_frames)
    monkeypatch.setattr(worker, "_tool_version", lambda *args: "test")
    monkeypatch.setattr(
        worker, "_ocr_bytes", lambda *args: {"text": "Frame text", "words": []}
    )
    return worker, batches, paths


@pytest.mark.asyncio
@pytest.mark.parametrize("audio,video", [(True, False), (False, True), (True, True)])
async def test_ingestion_batches_windows_and_combined_inputs(
    prepared_worker, monkeypatch, tmp_path, audio, video
):
    worker, batches, paths = prepared_worker
    monkeypatch.setattr(
        module, "probe_media", lambda _: MediaProbe(5, audio, video, False, "test")
    )
    monkeypatch.setattr(
        module, "window_ranges", lambda *args: [MediaWindow(i, i + 1) for i in range(5)]
    )
    _, records, versions = await worker._index_av_file(
        tmp_path / "source",
        "video/mp4" if video else "audio/wav",
        IngestionOptions(combined_media_text=True),
    )
    per_window = int(audio) + int(video) + 1
    count = 5 * per_window
    assert [len(batch) for _, batch in batches] == [4] * (count // 4) + (
        [count % 4] if count % 4 else []
    )
    assert all(kind == "ingestion" for kind, _ in batches)
    assert len(records) == count
    assert [record["start"] for record in records] == [
        i for i in range(5) for _ in range(per_window)
    ]
    for record in records:
        assert record["vector"][0] == (
            record["start"] if audio and record["kind"] != "video" else -1
        )
        assert record["vector"][1] == (record["kind"] == "combined")
    assert versions["combined_representations"] == 5
    assert versions["combined_context_failures"] == []
    assert paths and not any(path.exists() for path in paths)


@pytest.mark.asyncio
@pytest.mark.parametrize("include_embeddings", [True, False])
async def test_media_query_batches_all_windows_with_query_priority(
    prepared_worker, monkeypatch, include_embeddings
):
    worker, batches, paths = prepared_worker
    monkeypatch.setattr(
        module, "probe_media", lambda _: MediaProbe(60, True, True, False, "test")
    )
    result = await worker._prepare_media_query(
        b"source", "video/mp4", include_embeddings=include_embeddings
    )
    assert result["query_window_count"] == 3
    if include_embeddings:
        assert [len(batch) for _, batch in batches] == [4, 1]
        assert [kind for kind, _ in batches] == ["query", "query"]
        assert result["pooled_modalities"] == ["audio", "video"]
        assert result["vector"] is not None
    else:
        assert not batches
        assert result["vector"] is None
    assert paths and not any(path.exists() for path in paths)


def test_combined_batch_failure_is_isolated_without_losing_base_vectors():
    worker = Worker.__new__(Worker)
    seen = []

    class Model:
        def embed_media_batch(self, inputs):
            seen.append(len(inputs))
            if any(item.text == "too long" for item in inputs):
                raise ContextLimitError("processor budget exceeded")
            return [[float(item.audio_path.name)] for item in inputs]

    worker._model = lambda: Model()
    inputs = [
        MediaEmbeddingInput(
            audio_path=Path(str(i)), text="too long" if i == 1 else None
        )
        for i in range(3)
    ]
    assert worker._embed_media_batch(inputs) == [
        ([0.0], None),
        (None, "processor budget exceeded"),
        ([2.0], None),
    ]
    assert seen[0] == 3


def test_base_media_context_failure_remains_fatal():
    worker = Worker.__new__(Worker)

    class Model:
        def embed_media_batch(self, inputs):
            raise ContextLimitError("audio too long")

    worker._model = lambda: Model()
    with pytest.raises(ContextLimitError, match="audio too long"):
        worker._embed_media_batch([MediaEmbeddingInput(audio_path=Path("audio.wav"))])


@pytest.mark.asyncio
async def test_cancelled_batch_waits_for_inference_before_releasing_media():
    worker = Worker.__new__(Worker)
    started = asyncio.Event()
    release = asyncio.Event()

    class Scheduler:
        async def submit(self, *args, **kwargs):
            started.set()
            await release.wait()
            return [([1.0], None)]

    worker.scheduler = Scheduler()
    task = asyncio.create_task(
        worker._submit_media_batch(
            [MediaEmbeddingInput(audio_path=Path("audio.wav"))], kind="ingestion"
        )
    )
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
