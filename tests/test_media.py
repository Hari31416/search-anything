"""Focused tests for bounded local media decoding."""

from __future__ import annotations

import shutil
import subprocess
import json
import wave
from pathlib import Path

import pytest

from search_anything.ingestion import IngestionOptions
from search_anything.embeddings import ContextLimitError, audio_window_duration
from search_anything.media import (
    MAX_VIDEO_FRAMES_PER_WINDOW,
    MediaWindow,
    extract_video_frames,
    media_settings,
    probe_media,
    split_audio_window,
)


def test_custom_media_window_options_are_validated() -> None:
    options = IngestionOptions(
        media_window_seconds=12,
        media_overlap_seconds=2,
        video_sampling_fps=3,
    )
    resolved = media_settings(
        options.resolved_media_preset("video/mp4"),
        options.media_window_seconds,
        options.media_overlap_seconds,
        options.video_sampling_fps,
    )
    assert resolved == {
        "window_seconds": 12,
        "overlap_seconds": 2,
        "video_fps": 3,
    }
    with pytest.raises(ValueError, match="smaller"):
        IngestionOptions(media_window_seconds=10, media_overlap_seconds=10)
    with pytest.raises(ValueError):
        IngestionOptions(strategy="recursive")


def test_audio_subwindows_cover_the_full_window_with_overlap() -> None:
    parts = split_audio_window(MediaWindow(0, 300), overlap_seconds=5)
    assert parts[0].start == 0
    assert parts[-1].end == 300
    assert all(part.end - part.start <= 30 for part in parts)
    assert all(left.end >= right.start for left, right in zip(parts, parts[1:]))
    assert len(parts) > 10


def test_embedding_audio_guard_rejects_processor_clipping(tmp_path: Path) -> None:
    source = tmp_path / "too-long.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * (31 * 16000))
    with pytest.raises(ContextLimitError, match="31.000s"):
        audio_window_duration(source)


def test_attached_cover_art_is_not_a_video_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from search_anything import media

    responses = iter(
        [
            subprocess.CompletedProcess(
                [],
                0,
                json.dumps(
                    {
                        "format": {"duration": "4"},
                        "streams": [
                            {"codec_type": "audio", "duration": "4"},
                            {
                                "codec_type": "video",
                                "disposition": {"attached_pic": 1},
                            },
                        ],
                    }
                ),
                "",
            ),
            subprocess.CompletedProcess([], 0, "ffprobe version test", ""),
        ]
    )
    monkeypatch.setattr(media, "_run", lambda *_args, **_kwargs: next(responses))

    result = probe_media(Path("audio-with-cover.mp3"))
    assert result.has_audio
    assert not result.has_video
    assert result.has_attached_picture


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires local FFmpeg")
def test_video_frames_preserve_timestamps_after_nonzero_seek(tmp_path: Path) -> None:
    source = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=96x64:rate=12:duration=8",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source),
        ],
        check=True,
        timeout=30,
    )

    probe = probe_media(source)
    assert probe.has_video
    assert not probe.has_attached_picture

    frames = extract_video_frames(
        source,
        tmp_path / "frames",
        MediaWindow(3.0, 5.0),
        frames_per_second=30,
    )
    assert 1 < len(frames.paths) <= MAX_VIDEO_FRAMES_PER_WINDOW
    assert frames.effective_fps < 30
    assert frames.timestamps[0] >= 3.0
    assert frames.timestamps[-1] > 4.8
    assert all(3.0 <= timestamp <= 5.0 for timestamp in frames.timestamps)

    tail = extract_video_frames(
        source,
        tmp_path / "tail-frames",
        MediaWindow(7.0, 7.666667),
        frames_per_second=1,
    )
    assert tail.paths
    assert all(7.0 <= timestamp < 7.666667 for timestamp in tail.timestamps)

    short_source = tmp_path / "short.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=96x64:rate=12:duration=0.3",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(short_source),
        ],
        check=True,
        timeout=30,
    )
    short_probe = probe_media(short_source)
    short_frames = extract_video_frames(
        short_source,
        tmp_path / "short-frames",
        MediaWindow(0.0, short_probe.duration_seconds),
        frames_per_second=0.5,
    )
    assert len(short_frames.paths) == 1
