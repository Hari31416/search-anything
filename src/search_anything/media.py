"""Bounded FFmpeg/Whisper media windows for local audio and video ingestion."""

from __future__ import annotations

import hashlib
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from search_anything.embeddings import MAX_AUDIO_SECONDS
from search_anything.devices import InferenceDevice, resolve_device

WHISPER_MODEL_SHA256 = (
    "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9"
)
MAX_VIDEO_FRAMES_PER_WINDOW = 32
MAX_AUDIO_WINDOW_SECONDS = MAX_AUDIO_SECONDS
MAX_MEDIA_DURATION_SECONDS = 24 * 60 * 60
PRESETS: dict[str, dict[str, float]] = {
    "speech_lectures": {
        "window_seconds": 30.0,
        "overlap_seconds": 5.0,
        "video_fps": 0.5,
    },
    "general_video": {"window_seconds": 20.0, "overlap_seconds": 5.0, "video_fps": 1.0},
    "music_sounds": {"window_seconds": 15.0, "overlap_seconds": 3.0, "video_fps": 0.5},
    "camera_footage": {
        "window_seconds": 10.0,
        "overlap_seconds": 3.0,
        "video_fps": 1.0,
    },
}


class MediaProcessingError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MediaProbe:
    duration_seconds: float
    has_audio: bool
    has_video: bool
    has_attached_picture: bool
    ffprobe_version: str


@dataclass(frozen=True)
class MediaWindow:
    start: float
    end: float


@dataclass(frozen=True)
class DecodedFrames:
    paths: list[Path]
    timestamps: list[float]
    effective_fps: float


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise MediaProcessingError(
            "ffmpeg_unavailable", "FFmpeg is not installed"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise MediaProcessingError(
            "media_timeout", "FFmpeg exceeded its processing time limit"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (
            error.stderr.strip().splitlines()[-1] if error.stderr else "decoder failed"
        )
        raise MediaProcessingError("media_decode_failed", detail[:500]) from error


def probe_media(path: Path) -> MediaProbe:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        timeout=60,
    )
    import json

    metadata = json.loads(result.stdout)
    duration = float((metadata.get("format") or {}).get("duration") or 0)
    for stream in metadata.get("streams", []):
        stream_duration = stream.get("duration")
        if not duration and stream_duration:
            duration = max(duration, float(stream_duration))
    if not math.isfinite(duration) or duration <= 0:
        raise MediaProcessingError(
            "invalid_duration", "Media duration is missing or invalid"
        )
    if duration > MAX_MEDIA_DURATION_SECONDS:
        raise MediaProcessingError(
            "duration_limit_exceeded", "Media exceeds the 24-hour duration limit"
        )
    version = _run(["ffprobe", "-version"], timeout=10).stdout.splitlines()[0]
    streams = metadata.get("streams", [])
    real_video = [
        stream
        for stream in streams
        if stream.get("codec_type") == "video"
        and not (stream.get("disposition") or {}).get("attached_pic", 0)
    ]
    return MediaProbe(
        duration,
        any(stream.get("codec_type") == "audio" for stream in streams),
        bool(real_video),
        any(
            stream.get("codec_type") == "video"
            and (stream.get("disposition") or {}).get("attached_pic", 0)
            for stream in streams
        ),
        version,
    )


def media_settings(
    preset: str,
    window_seconds: float | None = None,
    overlap_seconds: float | None = None,
    video_sampling_fps: float | None = None,
) -> dict[str, float]:
    selected = PRESETS.get(preset)
    if selected is None:
        raise MediaProcessingError(
            "unknown_preset", f"Unsupported media preset: {preset}"
        )
    result = {
        "window_seconds": window_seconds or selected["window_seconds"],
        "overlap_seconds": (
            overlap_seconds
            if overlap_seconds is not None
            else selected["overlap_seconds"]
        ),
        "video_fps": video_sampling_fps or selected["video_fps"],
    }
    if result["overlap_seconds"] >= result["window_seconds"]:
        raise MediaProcessingError(
            "invalid_preset", "Media overlap must be smaller than the window"
        )
    return result


def window_ranges(
    duration: float,
    preset: str,
    window_seconds: float | None = None,
    overlap_seconds: float | None = None,
) -> list[MediaWindow]:
    selected = media_settings(preset, window_seconds, overlap_seconds)
    window = selected["window_seconds"]
    step = window - selected["overlap_seconds"]
    if step <= 0:
        raise MediaProcessingError(
            "invalid_preset", "Media overlap must be smaller than the window"
        )
    result: list[MediaWindow] = []
    start = 0.0
    while start < duration:
        result.append(MediaWindow(start, min(duration, start + window)))
        start += step
    return result


def split_audio_window(
    window: MediaWindow,
    overlap_seconds: float,
    max_window_seconds: float = MAX_AUDIO_WINDOW_SECONDS,
) -> list[MediaWindow]:
    if max_window_seconds <= 0 or overlap_seconds < 0:
        raise MediaProcessingError(
            "invalid_audio_window", "Audio window settings are invalid"
        )
    if overlap_seconds >= max_window_seconds:
        raise MediaProcessingError(
            "invalid_audio_window",
            "Audio overlap must be smaller than the audio window",
        )
    step = max_window_seconds - overlap_seconds
    result: list[MediaWindow] = []
    start = window.start
    while start < window.end:
        end = min(window.end, start + max_window_seconds)
        result.append(MediaWindow(start, end))
        if end >= window.end:
            break
        start += step
    return result


def extract_audio_window(source: Path, output: Path, window: MediaWindow) -> None:
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{window.start:.6f}",
            "-i",
            str(source),
            "-t",
            f"{window.end - window.start:.6f}",
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(output),
        ],
        timeout=max(30.0, (window.end - window.start) * 10),
    )
    if not output.is_file() or output.stat().st_size == 0:
        raise MediaProcessingError(
            "empty_audio_window", "FFmpeg produced an empty audio window"
        )


def extract_video_frames(
    source: Path,
    output_dir: Path,
    window: MediaWindow,
    frames_per_second: float,
) -> DecodedFrames:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = output_dir / "frame-%03d.png"
    window_duration = window.end - window.start
    # Leave one frame of headroom for inclusive endpoint rounding by FFmpeg.
    effective_fps = min(
        max(frames_per_second, 1.0 / window_duration),
        (MAX_VIDEO_FRAMES_PER_WINDOW - 1) / window_duration,
    )
    result = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "info",
            "-ss",
            f"{window.start:.6f}",
            "-i",
            str(source),
            "-vf",
            f"trim=duration={window_duration:.9f},setpts=PTS-STARTPTS+{window.start:.9f}/TB,fps={effective_fps:.9f},showinfo",
            "-frames:v",
            str(MAX_VIDEO_FRAMES_PER_WINDOW),
            "-fps_mode",
            "passthrough",
            "-y",
            str(output_pattern),
        ],
        timeout=max(30.0, (window.end - window.start) * 10),
    )
    paths = sorted(output_dir.glob("frame-*.png"))
    raw_times = [
        float(value)
        for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr)
    ]
    if len(raw_times) != len(paths):
        raise MediaProcessingError(
            "frame_timestamps_missing",
            "FFmpeg did not report every decoded frame timestamp",
        )
    timestamps = raw_times
    if len(paths) > MAX_VIDEO_FRAMES_PER_WINDOW:
        raise MediaProcessingError(
            "frame_limit_exceeded", "FFmpeg exceeded the per-window frame limit"
        )
    if any(
        timestamp < window.start - 0.05 or timestamp > window.end + 0.05
        for timestamp in timestamps
    ):
        raise MediaProcessingError(
            "frame_timestamp_invalid", "Decoded frame timestamp is outside its window"
        )
    return DecodedFrames(paths, timestamps, effective_fps)


def verify_whisper_checkpoint(path: Path) -> None:
    if not path.is_file():
        raise MediaProcessingError(
            "whisper_checkpoint_missing",
            f"Pinned local Whisper checkpoint is unavailable at {path}",
        )
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    digest = checksum.hexdigest()
    if digest != WHISPER_MODEL_SHA256:
        raise MediaProcessingError(
            "whisper_checkpoint_mismatch",
            "Whisper checkpoint checksum did not match the pinned tiny model",
        )


def _whisper_dtw_cpu(matrix: Any) -> Any:
    """Whisper's timing alignment needs float64, which MPS cannot represent."""
    from whisper.timing import dtw_cpu

    return dtw_cpu(matrix.cpu().double().numpy())


def load_whisper(path: Path, device: InferenceDevice = "auto") -> Any:
    verify_whisper_checkpoint(path)
    import whisper

    selected = resolve_device(device)
    model = whisper.load_model(str(path), device="cpu")
    if selected == "mps":
        # Whisper's word timing code reads sparse indices. Keep that tiny mask
        # on CPU while transferring the actual inference weights to MPS.
        alignment_heads = model.alignment_heads
        model.register_buffer(
            "alignment_heads", model.alignment_heads.to_dense(), persistent=False
        )
        model.to(selected)
        model.register_buffer("alignment_heads", alignment_heads, persistent=False)
        # Upstream converts to float64 before transferring to CPU. Transfer
        # first so word timestamps remain available with GPU inference.
        whisper.timing.dtw = _whisper_dtw_cpu
    return model


def transcribe_window(
    model: Any, audio_path: Path, language: str | None = None
) -> dict[str, Any]:
    try:
        return model.transcribe(
            str(audio_path),
            fp16=False,
            language=language,
            verbose=False,
            condition_on_previous_text=False,
            word_timestamps=True,
        )
    except Exception as error:
        raise MediaProcessingError(
            "transcription_failed", "Local Whisper transcription failed"
        ) from error
