"""Exercise pinned local models without contacting inference APIs."""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from sentence_transformers import SentenceTransformer

MODEL_REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
DIMENSIONS = 768


def make_fixtures(directory: Path) -> tuple[Path, Path]:
    image_path = directory / "fire-truck.png"
    image = Image.new("RGB", (640, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 500, 240), fill="#d82323")
    draw.rectangle((170, 50, 380, 110), fill="#d82323")
    draw.rectangle((205, 65, 270, 105), fill="#a8d9f0")
    draw.rectangle((285, 65, 350, 105), fill="#a8d9f0")
    draw.ellipse((155, 210, 245, 300), fill="#222222")
    draw.ellipse((365, 210, 455, 300), fill="#222222")
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 36)
    draw.text((100, 5), "FIRE TRUCK", fill="black", font=font)
    image.save(image_path)

    audio_path = directory / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-y",
            str(audio_path),
        ],
        check=True,
    )
    video_path = directory / "fire-truck.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-framerate",
            "1",
            "-i",
            str(image_path),
            "-t",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-y",
            str(video_path),
        ],
        check=True,
    )
    return image_path, audio_path


def validate_vector(vector: Any) -> dict[str, Any]:
    values = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(values))
    if values.shape != (DIMENSIONS,):
        raise ValueError(f"expected {DIMENSIONS} dimensions, got {values.shape}")
    if not np.isfinite(values).all() or not 0.98 <= norm <= 1.02:
        raise ValueError(f"invalid embedding values or norm: {norm}")
    return {"dimensions": int(values.size), "l2_norm": norm}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding-model-path", type=Path, required=True)
    parser.add_argument("--whisper-checkpoint", type=Path)
    parser.add_argument("--whisper-model", default="tiny")
    args = parser.parse_args()

    model_path = args.embedding_model_path.resolve()
    if model_path.name != MODEL_REVISION:
        raise ValueError(
            "embedding model path must be the pinned Hugging Face snapshot "
            f"{MODEL_REVISION}"
        )

    if torch.backends.mps.is_available():
        device = "mps"
        dtype = torch.float32
    else:
        device = "cpu"
        dtype = torch.float32

    started = time.perf_counter()
    model = SentenceTransformer(
        str(model_path),
        device=device,
        model_kwargs={"torch_dtype": dtype},
    )
    load_seconds = time.perf_counter() - started

    with tempfile.TemporaryDirectory(prefix="search-anything-model-smoke-") as temp:
        directory = Path(temp)
        image_path, audio_path = make_fixtures(directory)
        video_path = directory / "fire-truck.mp4"
        decoded_frames = directory / "frames"
        decoded_frames.mkdir()
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-vf",
                "fps=1",
                str(decoded_frames / "frame-%02d.png"),
            ],
            check=True,
        )
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        frames = [
            Image.open(frame_path).convert("RGB")
            for frame_path in sorted(decoded_frames.glob("frame-*.png"))
        ]
        if not frames:
            raise ValueError("ffmpeg did not decode any video frames")
        cases: dict[str, Any] = {
            "text": "task: search result | query: find a fire truck",
            "image": image,
            "audio": {"text": "<|audio|>", "audio": str(audio_path)},
            "video": {"text": "<|video|>", "video": [frames]},
            "text_image": {
                "text": "Fire truck <|image|>",
                "image": image,
            },
            "combined": {
                "text": "Fire truck <|image|> <|audio|> <|video|>",
                "image": image,
                "audio": str(audio_path),
                "video": [frames],
            },
        }
        timings: dict[str, Any] = {}
        for name, value in cases.items():
            started = time.perf_counter()
            vector = model.encode(value, normalize_embeddings=True)
            timings[name] = {
                **validate_vector(vector),
                "seconds": round(time.perf_counter() - started, 3),
            }
            if name == "text":
                text_query_vector = np.asarray(vector, dtype=np.float32)
            elif name == "image":
                image_vector = np.asarray(vector, dtype=np.float32)

        distractor_vector = np.asarray(
            model.encode(
                "task: search result | query: find a tennis ball",
                normalize_embeddings=True,
            ),
            dtype=np.float32,
        )
        cross_modal_scores = {
            "fire_truck_query_to_image": float(text_query_vector @ image_vector),
            "tennis_ball_query_to_image": float(distractor_vector @ image_vector),
        }

        ocr = subprocess.run(
            ["tesseract", str(image_path), "stdout", "-l", "eng", "--psm", "6"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if "FIRE" not in ocr.upper() or "TRUCK" not in ocr.upper():
            raise ValueError(f"Tesseract failed to read fixture text: {ocr!r}")

        whisper_result: dict[str, Any] | None = None
        if args.whisper_checkpoint:
            import whisper

            started = time.perf_counter()
            speech_model = whisper.load_model(
                str(args.whisper_checkpoint), device="cpu"
            )
            whisper_load_seconds = time.perf_counter() - started
            started = time.perf_counter()
            transcription = speech_model.transcribe(
                str(audio_path), fp16=False, language="en"
            )
            whisper_result = {
                "model": args.whisper_model,
                "device": "cpu",
                "load_seconds": round(whisper_load_seconds, 3),
                "transcribe_seconds": round(time.perf_counter() - started, 3),
                "text": transcription["text"].strip(),
            }

        # On macOS ru_maxrss is reported in bytes.
        peak_rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024**2)
        report = {
            "embedding_model": "google/embeddinggemma-2",
            "revision": MODEL_REVISION,
            "device": device,
            "dtype": str(dtype).removeprefix("torch."),
            "load_seconds": round(load_seconds, 3),
            "peak_rss_mib": round(peak_rss_mib, 1),
            "embeddings": timings,
            "cross_modal_scores": cross_modal_scores,
            "ocr_text": ocr,
            "whisper": whisper_result,
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
