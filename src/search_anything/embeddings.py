"""Offline EmbeddingGemma adapter with actual processor budget checks."""

from __future__ import annotations

import os
import wave
from pathlib import Path
from typing import Any, Sequence, Protocol

import numpy as np

from search_anything.devices import InferenceDevice, resolve_device

MODEL_ID = "google/embeddinggemma-2"
MODEL_REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
DIMENSIONS = 768
MAX_AUDIO_SECONDS = 30.0


class EmbeddingError(RuntimeError):
    pass


class ContextLimitError(EmbeddingError):
    pass


def audio_window_duration(audio_path: Path) -> float:
    try:
        with wave.open(str(audio_path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
    except (OSError, wave.Error, ZeroDivisionError) as error:
        raise EmbeddingError(
            "audio embeddings require a readable PCM WAV input"
        ) from error
    if duration > MAX_AUDIO_SECONDS:
        raise ContextLimitError(
            f"audio is {duration:.3f}s; model audio windows are limited to "
            f"{MAX_AUDIO_SECONDS:.0f}s to avoid processor truncation"
        )
    return duration


class TextTokenCounter(Protocol):
    context_tokens: int

    def count_text_tokens(self, text: str) -> int: ...

    def text_token_offsets(self, text: str) -> list[tuple[int, int]]: ...


class LocalEmbeddingModel:
    """Own one local float32 model and validate its processor budget."""

    def __init__(
        self,
        model_path: Path,
        revision: str = MODEL_REVISION,
        context_tokens: int = 8192,
        batch_size: int = 8,
        device: InferenceDevice = "auto",
    ) -> None:
        if revision != MODEL_REVISION:
            raise EmbeddingError(f"unsupported embedding revision: {revision}")
        model_path = model_path.expanduser().resolve()
        if not model_path.is_dir() or model_path.name != revision:
            raise EmbeddingError(
                f"pinned local model snapshot is unavailable at {model_path}"
            )
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        import torch
        from sentence_transformers import SentenceTransformer

        self.context_tokens = context_tokens
        self.batch_size = batch_size
        self.device = resolve_device(device)
        self.model = SentenceTransformer(
            str(model_path),
            device=self.device,
            model_kwargs={"torch_dtype": torch.float32},
            local_files_only=True,
        )
        self.tokenizer = self.model.tokenizer

    def _processed(self, value: Any, *, prompt: str | None = None) -> dict[str, Any]:
        processed = self.model.preprocess(
            [value],
            prompt=prompt,
            processing_kwargs={"text": {"truncation": False}},
        )
        input_ids = processed.get("input_ids")
        if input_ids is None:
            raise EmbeddingError("model processor did not return input token IDs")
        length = int(input_ids.shape[-1])
        if length > self.context_tokens:
            raise ContextLimitError(
                f"processed input has {length} tokens; limit is {self.context_tokens}"
            )
        return processed

    def count_text_tokens(self, text: str) -> int:
        processed = self._processed(text)
        return int(processed["input_ids"].shape[-1])

    def text_token_offsets(self, text: str) -> list[tuple[int, int]]:
        encoded = self.tokenizer(
            text,
            add_special_tokens=False,
            truncation=False,
            return_offsets_mapping=True,
        )
        return [tuple(pair) for pair in encoded["offset_mapping"]]

    def embed_texts(self, values: Sequence[str]) -> list[list[float]]:
        if not values:
            return []
        for value in values:
            self._processed(value)
        return self._encode(values)

    def embed_images(self, images: Sequence[Any]) -> list[list[float]]:
        if not images:
            return []
        for image in images:
            self._processed(image)
        return self._encode(images)

    def embed_audio(self, audio_path: Path) -> list[float]:
        audio_window_duration(audio_path)
        value = {"text": "<|audio|>", "audio": str(audio_path)}
        self._processed(value)
        return self._encode([value])[0]

    def embed_video(self, frames: Sequence[Any]) -> list[float]:
        if not frames:
            raise EmbeddingError("video embedding requires at least one frame")
        value = {"text": "<|video|>", "video": [list(frames)]}
        self._processed(value)
        return self._encode([value])[0]

    def embed_combined(
        self,
        text: str,
        *,
        image: Any | None = None,
        audio_path: Path | None = None,
        video_frames: Sequence[Any] | None = None,
    ) -> list[float]:
        """Embed text with its aligned media using the model's mixed-input schema."""
        clean = text.strip()
        if not clean:
            raise EmbeddingError("combined embedding requires aligned text")
        value: dict[str, Any] = {"text": clean}
        markers: list[str] = []
        if image is not None:
            value["image"] = image
            markers.append("<|image|>")
        if audio_path is not None:
            audio_window_duration(audio_path)
            value["audio"] = str(audio_path)
            markers.append("<|audio|>")
        if video_frames:
            value["video"] = [list(video_frames)]
            markers.append("<|video|>")
        if not markers:
            raise EmbeddingError("combined embedding requires at least one media input")
        value["text"] = f"{clean} {' '.join(markers)}"
        self._processed(value)
        return self._encode([value])[0]

    def _encode(self, values: Sequence[Any]) -> list[list[float]]:
        vectors = self.model.encode(
            list(values),
            batch_size=min(self.batch_size, len(values)),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            processing_kwargs={"text": {"truncation": False}},
        )
        array = np.asarray(vectors, dtype=np.float32)
        if array.shape != (len(values), DIMENSIONS):
            raise EmbeddingError(f"embedding output has invalid shape {array.shape}")
        if not np.isfinite(array).all():
            raise EmbeddingError("embedding output contains a non-finite value")
        norms = np.linalg.norm(array, axis=1)
        if not np.all((norms >= 0.98) & (norms <= 1.02)):
            raise EmbeddingError("embedding output is not normalized")
        return array.tolist()

    def embed_query(self, text: str) -> list[float]:
        clean = text.strip()
        if not clean:
            raise EmbeddingError("query text cannot be empty")
        formatted = f"task: search result | query: {clean}"
        self._processed(formatted)
        return self._encode([formatted])[0]


def document_embedding_text(title: str | None, text: str) -> str:
    clean_title = " ".join((title or "none").split()) or "none"
    return f"title: {clean_title} | text: {text.strip()}"
