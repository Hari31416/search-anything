"""Unit checks for bounded and failure-tolerant model queries."""

from __future__ import annotations

import pytest

from search_anything.embeddings import ContextLimitError
from search_anything.worker import Worker


def test_media_query_windows_cover_edges_with_a_fixed_bound() -> None:
    windows = Worker._bounded_query_windows(120, 30, modality="audio")
    assert len(windows) == 4
    assert windows[0].start == 0
    assert windows[-1].end == 120
    assert all(window.end - window.start <= 30 for window in windows)
    assert all(left.end >= right.start for left, right in zip(windows, windows[1:]))

    video_windows = Worker._bounded_query_windows(80, 20, modality="video")
    assert len(video_windows) == 4
    assert video_windows[0].start == 0
    assert video_windows[-1].end == 80
    assert all(
        left.end >= right.start for left, right in zip(video_windows, video_windows[1:])
    )


@pytest.mark.parametrize(
    ("duration", "window_seconds", "modality", "maximum"),
    [(120.1, 30, "audio", "120 seconds"), (80.1, 20, "video", "80 seconds")],
)
def test_media_query_windows_reject_incomplete_coverage(
    duration: float, window_seconds: float, modality: str, maximum: str
) -> None:
    with pytest.raises(ValueError, match=maximum):
        Worker._bounded_query_windows(duration, window_seconds, modality=modality)


def test_media_query_pooling_does_not_weight_duplicate_windows() -> None:
    one_window = Worker._pool_query_vectors([[1.0, 0.0]])
    many_same_windows = Worker._pool_query_vectors([[1.0, 0.0]] * 4)
    assert many_same_windows == one_window

    pooled_audio = Worker._pool_query_vectors([[1.0, 0.0]] * 4)
    pooled_video = Worker._pool_query_vectors([[0.0, 1.0]])
    balanced_modalities = Worker._pool_query_vectors([pooled_audio, pooled_video])
    assert balanced_modalities == pytest.approx([2**-0.5, 2**-0.5])


@pytest.mark.asyncio
async def test_combined_context_failure_is_reported_without_failing_base_work() -> None:
    class Scheduler:
        async def submit(self, *_args, **_kwargs):
            raise ContextLimitError("combined payload exceeds the processor budget")

    worker = Worker.__new__(Worker)
    worker.scheduler = Scheduler()
    vector, failure = await worker._try_embed_combined("local text", kind="ingestion")
    assert vector is None
    assert failure == "combined payload exceeds the processor budget"


@pytest.mark.asyncio
async def test_av_indexing_preserves_whisper_confidence_without_tail_window(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace
    from search_anything import worker as module
    from search_anything.media import MediaProbe
    from search_anything.ingestion import IngestionOptions, chunk_blocks

    signals = dict(avg_logprob=-0.4, no_speech_prob=0.02, compression_ratio=1.3)
    calls = []

    class Scheduler:
        async def submit(self, function, *args, **kwargs):
            calls.append(function.__name__)
            if function.__name__ == "_transcribe":
                return dict(
                    language="en",
                    segments=[
                        dict(text="The moon orbits Earth.", start=2, end=4, **signals)
                    ],
                )
            return [([0.0] * 768, None) for _ in args[0]]

    worker = Worker.__new__(Worker)
    worker.scheduler = Scheduler()
    worker.settings = SimpleNamespace(whisper_model_name="tiny")
    monkeypatch.setattr(
        module, "probe_media", lambda _: MediaProbe(30, True, False, False, "test")
    )
    monkeypatch.setattr(
        module,
        "extract_audio_window",
        lambda source, path, window: path.write_bytes(b"audio"),
    )
    monkeypatch.setattr(worker, "_tool_version", lambda *args: "test")
    blocks, records, versions = await worker._index_av_file(
        tmp_path / "audio.wav", "audio/wav", IngestionOptions()
    )
    assert calls.count("_transcribe") == 1
    assert len(records) == 1
    assert versions["audio_windows"] == 1
    assert blocks[0].location["whisper_confidence"] == signals
    assert (blocks[0].time_start, blocks[0].time_end) == (2, 4)

    class TokenBudget:
        context_tokens = 8192

        def count_text_tokens(self, text):
            return len(text.split())

    chunks = chunk_blocks(blocks, "opaque.wav", TokenBudget(), 700, 80)
    assert chunks[0].location["whisper_confidence"] == signals
