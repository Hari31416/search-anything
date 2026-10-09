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
