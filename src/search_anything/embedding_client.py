"""HTTP embedding adapter with a pinned tokenizer for local chunk planning."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Sequence

import httpx
import numpy as np
from PIL import Image

from search_anything.embeddings import (
    DIMENSIONS,
    MODEL_ID,
    MODEL_REVISION,
    ContextLimitError,
    EmbeddingError,
    MediaEmbeddingInput,
    audio_window_duration,
)


class EmbeddingContractError(EmbeddingError):
    """The service cannot safely produce embeddings for the current index."""


class EmbeddingInputError(EmbeddingError, ValueError):
    """The service rejected an input that should not be retried unchanged."""


class LocalTextTokenizer:
    """Load tokenizer files only, without model weights or a model processor."""

    def __init__(self, model_path: Path, revision: str, context_tokens: int) -> None:
        if revision != MODEL_REVISION:
            raise EmbeddingContractError(f"unsupported embedding revision: {revision}")
        model_path = model_path.expanduser().resolve()
        if not model_path.is_dir() or model_path.name != revision:
            raise EmbeddingContractError(
                f"pinned tokenizer snapshot unavailable at {model_path}"
            )
        from transformers import AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(
            str(model_path), local_files_only=True
        )
        self.context_tokens = context_tokens

    def count_text_tokens(self, text: str) -> int:
        count = len(
            self.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"]
        )
        if count > self.context_tokens:
            raise ContextLimitError(
                f"text has {count} tokens; limit is {self.context_tokens}"
            )
        return count

    def text_token_offsets(self, text: str) -> list[tuple[int, int]]:
        result = self.tokenizer(
            text,
            add_special_tokens=False,
            truncation=False,
            return_offsets_mapping=True,
        )
        return [tuple(pair) for pair in result["offset_mapping"]]


@dataclass(frozen=True)
class _MediaFile:
    filename: str
    data: bytes
    content_type: str


class RemoteEmbeddingModel:
    """Keep the worker's embedding interface while inference runs in the service.

    Calls are synchronous because the worker runs them in its priority scheduler.
    Transient failures propagate to the durable job retry mechanism.
    """

    def __init__(
        self,
        model_path: Path,
        revision: str = MODEL_REVISION,
        context_tokens: int = 8192,
        batch_size: int = 8,
        *,
        base_url: str = "http://127.0.0.1:8001",
        timeout_seconds: float = 120,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.text = LocalTextTokenizer(model_path, revision, context_tokens)
        self.context_tokens = context_tokens
        self.batch_size = batch_size
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(timeout_seconds, connect=min(5, timeout_seconds)),
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            trust_env=False,
        )
        try:
            ready = self._request("GET", "health/ready")
            if ready.get("status") != "ready":
                raise EmbeddingError("embedding service is not ready")
            metadata = self._request("GET", "v1/models")
            models = metadata.get("data", [])
            if not isinstance(models, list) or not all(
                isinstance(model, dict) for model in models
            ):
                raise EmbeddingContractError(
                    "embedding service returned invalid model metadata"
                )
            model = next((m for m in models if m.get("id") == MODEL_ID), None)
            if (
                model is None
                or model.get("revision") != revision
                or DIMENSIONS not in model.get("output_dimensions", [])
            ):
                raise EmbeddingContractError(
                    "embedding service model, revision, or dimensions do not match the index"
                )
            if model.get("test_mode") is not False:
                raise EmbeddingContractError(
                    "embedding service must report test_mode=false before indexing"
                )
            limits = model.get("configured_limits", {})
            if not isinstance(limits, dict):
                raise EmbeddingContractError(
                    "embedding service returned invalid limits"
                )
            if limits.get("max_context_tokens") != context_tokens:
                raise EmbeddingContractError(
                    "embedding service context limit does not match SEARCH_EMBEDDING_CONTEXT_TOKENS"
                )
            if (
                limits.get("vision_max_soft_tokens") != 280
                or limits.get("video_max_soft_tokens") != 140
            ):
                raise EmbeddingContractError(
                    "embedding service visual token budgets do not match the pinned index"
                )
            try:
                self.batch_size = min(batch_size, int(limits["max_batch_size"]))
                self.max_upload_bytes = int(limits["max_upload_bytes"])
                self.max_video_frames = int(limits["max_video_frames"])
                self.max_request_bytes = int(
                    limits.get("max_embedding_request_bytes", 104857600)
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise EmbeddingContractError(
                    "embedding service reported invalid limits"
                ) from exc
            if (
                min(
                    self.batch_size,
                    self.max_upload_bytes,
                    self.max_video_frames,
                    self.max_request_bytes,
                )
                <= 0
            ):
                raise EmbeddingContractError(
                    "embedding service reported invalid limits"
                )
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise EmbeddingError(
                f"embedding service request failed: {type(exc).__name__}"
            ) from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise EmbeddingError(
                f"embedding service returned non-JSON response, HTTP {response.status_code}"
            ) from exc
        if not isinstance(data, dict):
            raise EmbeddingContractError(
                "embedding service returned an invalid response"
            )
        if response.is_error:
            error = data.get("error", {})
            code = (
                error.get("code", "unknown") if isinstance(error, dict) else "unknown"
            )
            if response.status_code == 413 and path == "v1/embeddings":
                raise ContextLimitError(
                    "embedding input exceeds service processor limits"
                )
            if response.status_code in {400, 413, 422}:
                raise EmbeddingInputError(f"embedding service rejected input: {code}")
            raise EmbeddingError(
                f"embedding service returned HTTP {response.status_code}: {code}"
            )
        return data

    def count_text_tokens(self, text: str) -> int:
        return self.text.count_text_tokens(text)

    def text_token_offsets(self, text: str) -> list[tuple[int, int]]:
        return self.text.text_token_offsets(text)

    def _media_file(self, data: bytes, filename: str, content_type: str) -> _MediaFile:
        if len(data) > self.max_upload_bytes:
            raise EmbeddingInputError("prepared media exceeds service upload limit")
        return _MediaFile(filename, data, content_type)

    def _image_file(self, image: Any) -> _MediaFile:
        if not isinstance(image, Image.Image):
            image = Image.fromarray(np.asarray(image))
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        return self._media_file(buffer.getvalue(), "frame.png", "image/png")

    def _frames_part(self, frames: Sequence[Any]) -> dict[str, Any]:
        if not frames:
            raise EmbeddingInputError("video embedding requires at least one frame")
        if len(frames) > self.max_video_frames:
            raise ContextLimitError("video frame group exceeds service frame limit")
        return {
            "type": "video_frames",
            "files": [self._image_file(frame) for frame in frames],
        }

    def _audio_part(self, path: Path) -> dict[str, Any]:
        audio_window_duration(path)
        if path.stat().st_size > self.max_upload_bytes:
            raise EmbeddingInputError("prepared audio exceeds service upload limit")
        return {
            "type": "media",
            "file": self._media_file(path.read_bytes(), "window.wav", "audio/wav"),
        }

    @staticmethod
    def _request_inputs(items: list[dict[str, Any]]) -> dict[str, Any]:
        files: dict[str, tuple[str, bytes, str]] = {}

        def attach(media: _MediaFile) -> str:
            name = f"media_{len(files)}"
            files[name] = (media.filename, media.data, media.content_type)
            return name

        wire_items = []
        for item in items:
            wire_parts = []
            for part in item["parts"]:
                wire_part = dict(part)
                if part["type"] == "media" and isinstance(part.get("file"), _MediaFile):
                    wire_part["file"] = attach(part["file"])
                elif part["type"] == "video_frames" and "files" in part:
                    wire_part["files"] = [attach(frame) for frame in part["files"]]
                wire_parts.append(wire_part)
            wire_items.append({"id": item["id"], "parts": wire_parts})
        payload = {
            "items": wire_items,
            "task": "document",
            "prompt_mode": "none",
            "truncate_dim": DIMENSIONS,
        }
        if files:
            return {"data": {"payload": json.dumps(payload)}, "files": files}
        return {"json": payload}

    def _request_batches(self, parts: list[list[dict[str, Any]]]):
        items = []
        inputs = None
        for value in parts:
            candidate = [*items, {"id": str(len(items)), "parts": value}]
            candidate_inputs = self._request_inputs(candidate)
            request = self._client.build_request(
                "POST", "v1/embeddings", **candidate_inputs
            )
            fits = (
                len(candidate) <= self.batch_size
                and len(candidate_inputs.get("files", {})) <= 128
                and int(request.headers["content-length"]) <= self.max_request_bytes
            )
            if not fits and items:
                yield items, inputs
                candidate = [{"id": "0", "parts": value}]
                candidate_inputs = self._request_inputs(candidate)
                request = self._client.build_request(
                    "POST", "v1/embeddings", **candidate_inputs
                )
            if (
                len(candidate_inputs.get("files", {})) > 128
                or int(request.headers["content-length"]) > self.max_request_bytes
            ):
                raise EmbeddingInputError("prepared item exceeds service request limit")
            items, inputs = candidate, candidate_inputs
        if items:
            yield items, inputs

    def _embed(self, parts: list[list[dict[str, Any]]]) -> list[list[float]]:
        if not parts:
            return []
        result = []
        for items, inputs in self._request_batches(parts):
            data = self._request("POST", "v1/embeddings", **inputs)
            if (
                data.get("model") != MODEL_ID
                or data.get("revision") != MODEL_REVISION
                or data.get("dimension") != DIMENSIONS
                or data.get("normalized") is not True
            ):
                raise EmbeddingContractError(
                    "embedding response does not match the index contract"
                )
            rows = data.get("embeddings", [])
            if not isinstance(rows, list) or not all(
                isinstance(row, dict) for row in rows
            ):
                raise EmbeddingContractError("embedding response contains invalid rows")
            if len(rows) != len(items) or [row.get("id") for row in rows] != [
                item["id"] for item in items
            ]:
                raise EmbeddingContractError(
                    "embedding response omitted or reordered items"
                )
            try:
                vectors = np.asarray(
                    [row["embedding"] for row in rows], dtype=np.float32
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise EmbeddingContractError(
                    "embedding response contains invalid vectors"
                ) from exc
            if (
                vectors.shape != (len(items), DIMENSIONS)
                or not np.isfinite(vectors).all()
            ):
                raise EmbeddingContractError(
                    "embedding response contains invalid shape or values"
                )
            norms = np.linalg.norm(vectors, axis=1)
            if not np.all((norms >= 0.98) & (norms <= 1.02)):
                raise EmbeddingContractError("embedding response is not normalized")
            result.extend(vectors.tolist())
        return result

    def embed_texts(self, values: Sequence[str]) -> list[list[float]]:
        for text in values:
            self.count_text_tokens(text)
        return self._embed([[{"type": "text", "text": text}] for text in values])

    def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise EmbeddingInputError("query text cannot be empty")
        return self.embed_texts([f"task: search result | query: {text.strip()}"])[0]

    def embed_images(self, images: Sequence[Any]) -> list[list[float]]:
        return self._embed(
            [[{"type": "media", "file": self._image_file(image)}] for image in images]
        )

    def embed_media_batch(
        self, inputs: Sequence[MediaEmbeddingInput]
    ) -> list[list[float]]:
        parts = []
        for item in inputs:
            value = []
            if item.text:
                value.append({"type": "text", "text": item.text})
            if item.audio_path is not None:
                value.append(self._audio_part(item.audio_path))
            if item.frame_paths:
                with item.open_frames() as frames:
                    value.append(self._frames_part(frames))
            if not item.paths:
                raise EmbeddingInputError(
                    "media embedding requires audio or video frames"
                )
            parts.append(value)
        return self._embed(parts)

    def embed_audio(self, audio_path: Path) -> list[float]:
        return self._embed([[self._audio_part(audio_path)]])[0]

    def embed_video(self, frames: Sequence[Any]) -> list[float]:
        return self._embed([[self._frames_part(frames)]])[0]

    def embed_combined(
        self,
        text: str,
        *,
        image: Any | None = None,
        audio_path: Path | None = None,
        video_frames: Sequence[Any] | None = None,
    ) -> list[float]:
        if not text.strip():
            raise EmbeddingInputError("combined embedding requires aligned text")
        parts: list[dict[str, Any]] = [{"type": "text", "text": text.strip()}]
        if image is not None:
            parts.append({"type": "media", "file": self._image_file(image)})
        if audio_path is not None:
            parts.append(self._audio_part(audio_path))
        if video_frames:
            parts.append(self._frames_part(video_frames))
        if len(parts) == 1:
            raise EmbeddingInputError(
                "combined embedding requires at least one media input"
            )
        return self._embed([parts])[0]
