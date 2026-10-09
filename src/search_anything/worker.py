"""Single-process owner for durable work and local model scheduling."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from search_anything.db import make_engine
from search_anything.jobs import (
    LeasedJob,
    LeaseLost,
    cancellation_requested,
    claim_job,
    complete_job,
    fail_job,
    renew_lease,
    activate_generation,
)
from search_anything.models import (
    Asset,
    DerivedArtifact,
    Embedding,
    IngestionJob,
    Representation,
    ProcessingGeneration,
    Segment,
)
from search_anything.embeddings import (
    DIMENSIONS,
    MODEL_ID,
    MODEL_REVISION,
    LocalEmbeddingModel,
    document_embedding_text,
)
from search_anything.ingestion import (
    IngestionOptions,
    MAX_DOCUMENT_BYTES,
    TextBlock,
    TextChunk,
    chunk_blocks,
    extract_document,
)
from search_anything.media import (
    MAX_AUDIO_WINDOW_SECONDS,
    extract_audio_window,
    extract_video_frames,
    load_whisper,
    media_settings,
    probe_media,
    split_audio_window,
    transcribe_window,
    window_ranges,
)
from search_anything.scheduler import LocalInferenceScheduler
from search_anything.settings import Settings, get_settings
from search_anything.storage import S3ObjectStorage

logger = logging.getLogger(__name__)
JobHandler = Callable[[LeasedJob], Awaitable[None]]


class Worker:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        storage: S3ObjectStorage,
        scheduler: LocalInferenceScheduler | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.storage = storage
        self.scheduler = scheduler or LocalInferenceScheduler()
        self._embedding_model: LocalEmbeddingModel | None = None
        self._whisper_model: Any | None = None
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}"
        self.handlers: dict[str, JobHandler] = {
            "probe": self.probe_asset,
            "index": self.index_generation,
            "cleanup": self.cleanup_asset,
        }

    async def run(self) -> None:
        await self.scheduler.start()
        logger.info("Worker %s started", self.worker_id)
        try:
            while True:
                if not await self.run_once():
                    await asyncio.sleep(self.settings.job_poll_seconds)
        finally:
            await self.scheduler.close()

    async def run_once(self) -> bool:
        job = await claim_job(
            self.session_factory,
            self.worker_id,
            self.settings.job_lease_seconds,
        )
        if job is None:
            return False
        logger.info(
            "Claimed job %s stage=%s attempt=%s", job.id, job.stage, job.attempts
        )
        if await cancellation_requested(self.session_factory, job):
            await self.cancel_claim(job)
            return True
        handler = self.handlers.get(job.stage)
        if handler is None:
            await fail_job(
                self.session_factory,
                job,
                ValueError(f"unsupported job stage: {job.stage}"),
                retry_delay_seconds=0,
            )
            return True

        heartbeat = asyncio.create_task(self._heartbeat(job))
        try:
            await handler(job)
            if job.stage in {"cleanup", "index"}:
                pass
            elif await cancellation_requested(self.session_factory, job):
                await self.cancel_claim(job)
            else:
                await complete_job(self.session_factory, job)
        except LeaseLost:
            if await cancellation_requested(self.session_factory, job):
                await self.cancel_claim(job)
            logger.info("Discarded stale result from job %s", job.id)
        except Exception as error:
            delay = min(60.0, 2.0 ** min(job.attempts - 1, 6))
            try:
                await fail_job(self.session_factory, job, error, delay)
            except LeaseLost:
                logger.info("Stale worker could not record failure for job %s", job.id)
            logger.exception("Job %s failed", job.id)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, LeaseLost):
                await heartbeat
        return True

    async def _heartbeat(self, job: LeasedJob) -> None:
        interval = max(1.0, self.settings.job_lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            await renew_lease(
                self.session_factory,
                job,
                self.settings.job_lease_seconds,
                progress=0.5,
            )

    async def cancel_claim(self, job: LeasedJob) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(IngestionJob)
                .where(
                    IngestionJob.id == job.id,
                    IngestionJob.status == "running",
                    IngestionJob.lease_token == job.lease_token,
                    IngestionJob.cancellation_requested.is_(True),
                )
                .values(
                    status="cancelled",
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            await session.commit()

    async def probe_asset(self, job: LeasedJob) -> None:
        if job.asset_id is None or job.generation_id is None:
            raise ValueError("probe job is missing an asset or generation")
        async with self.session_factory() as session:
            asset = await session.get(Asset, job.asset_id)
            generation = await session.get(ProcessingGeneration, job.generation_id)
            if asset is None or generation is None or asset.state == "deleting":
                return
            key = asset.storage_key
            content_type = asset.content_type
        metadata: dict[str, object] = {}
        if content_type.startswith(("audio/", "video/")):
            stored = await self.storage.get_object(key)
            with tempfile.TemporaryDirectory(prefix="search-anything-probe-") as temp:
                local_path = Path(temp) / "source"

                def copy_source() -> None:
                    try:
                        with local_path.open("wb") as target:
                            shutil.copyfileobj(stored.body, target, length=1024 * 1024)
                    finally:
                        stored.body.close()

                await asyncio.to_thread(copy_source)
                result = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_format",
                        "-show_streams",
                        "-of",
                        "json",
                        str(local_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                metadata = json.loads(result.stdout)
                version_result = await asyncio.to_thread(
                    subprocess.run,
                    ["ffprobe", "-version"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                ffprobe_version = version_result.stdout.splitlines()[0].split()[2]
        async with self.session_factory() as session:
            async with session.begin():
                current_asset = await session.scalar(
                    select(Asset).where(Asset.id == job.asset_id).with_for_update()
                )
                current_job = await session.scalar(
                    select(IngestionJob)
                    .where(
                        IngestionJob.id == job.id,
                        IngestionJob.lease_token == job.lease_token,
                        IngestionJob.status == "running",
                        IngestionJob.lease_expires_at > datetime.now(timezone.utc),
                        IngestionJob.cancellation_requested.is_(False),
                    )
                    .with_for_update()
                )
                generation = await session.scalar(
                    select(ProcessingGeneration)
                    .where(ProcessingGeneration.id == job.generation_id)
                    .with_for_update()
                )
                if current_job is None or current_asset is None or generation is None:
                    raise LeaseLost(f"job {job.id} was reclaimed during probe")
                if (
                    current_asset.state == "deleting"
                    or current_job.cancellation_requested
                ):
                    return
                generation.extractor_versions = (
                    {"ffprobe": ffprobe_version} if metadata else {}
                )
                generation.state = "processing"
                if current_asset.active_generation_id is None:
                    current_asset.state = "processing"
                if metadata:
                    duration = (metadata.get("format") or {}).get("duration")
                    if duration is not None:
                        current_asset.duration_seconds = float(duration)
                await session.execute(
                    pg_insert(IngestionJob)
                    .values(
                        id=uuid4(),
                        asset_id=job.asset_id,
                        generation_id=job.generation_id,
                        stage="index",
                        status="queued",
                        priority=10,
                        payload={
                            "asset_id": str(job.asset_id),
                            "generation_id": str(job.generation_id),
                        },
                        idempotency_key=f"generation:{job.generation_id}:index",
                        max_attempts=self.settings.job_max_attempts,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[IngestionJob.idempotency_key]
                    )
                )

    def _model(self) -> LocalEmbeddingModel:
        if self._embedding_model is None:
            self._embedding_model = LocalEmbeddingModel(
                self.settings.embedding_model_path,
                self.settings.embedding_model_revision,
                self.settings.embedding_context_tokens,
                self.settings.embedding_batch_size,
            )
        return self._embedding_model

    def _plan_chunks(
        self, blocks: list[TextBlock], title: str, options: IngestionOptions
    ) -> list[TextChunk]:
        return chunk_blocks(
            blocks,
            title,
            self._model(),
            options.text_chunk_tokens,
            options.text_overlap_tokens,
        )

    def _embed_text_batch(self, texts: list[str]) -> list[list[float]]:
        return self._model().embed_texts(texts)

    def _embed_image(self, image: Any) -> list[float]:
        return self._model().embed_images([image])[0]

    def _embed_audio(self, path: Path) -> list[float]:
        return self._model().embed_audio(path)

    def _embed_video(self, frames: list[Any]) -> list[float]:
        return self._model().embed_video(frames)

    def _transcribe(self, path: Path, language: str | None) -> dict[str, Any]:
        if self._whisper_model is None:
            self._whisper_model = load_whisper(self.settings.whisper_checkpoint_path)
        return transcribe_window(self._whisper_model, path, language)

    async def _copy_object_to_path(self, key: str, destination: Path) -> None:
        stored = await self.storage.get_object(key)

        def copy() -> None:
            try:
                with destination.open("wb") as target:
                    shutil.copyfileobj(stored.body, target, length=1024 * 1024)
            finally:
                stored.body.close()

        await asyncio.to_thread(copy)

    async def _index_av_file(
        self,
        source: Path,
        content_type: str,
        options: IngestionOptions,
    ) -> tuple[list[TextBlock], list[dict[str, Any]], dict[str, Any]]:
        probe = await asyncio.to_thread(probe_media, source)
        is_video_asset = content_type.startswith("video/")
        if not probe.has_audio and not probe.has_video:
            raise ValueError("media file has no audio or video stream")
        preset = options.resolved_media_preset(content_type)
        sample = media_settings(
            preset,
            options.media_window_seconds,
            options.media_overlap_seconds,
            options.video_sampling_fps,
        )
        windows = window_ranges(
            probe.duration_seconds,
            preset,
            sample["window_seconds"],
            sample["overlap_seconds"],
        )
        text_blocks: list[TextBlock] = []
        media_records: list[dict[str, Any]] = []
        transcript_count = 0
        audio_window_count = 0
        frame_count = 0
        ocr_seen: dict[str, int] = {}
        transcription_language: str | None = None

        with tempfile.TemporaryDirectory(prefix="search-anything-av-") as temporary:
            temp = Path(temporary)
            for ordinal, window in enumerate(windows):
                if probe.has_audio:
                    audio_windows = split_audio_window(
                        window, sample["overlap_seconds"]
                    )
                    for audio_ordinal, audio_window in enumerate(audio_windows):
                        audio_path = (
                            temp / f"audio-{ordinal:06d}-{audio_ordinal:04d}.wav"
                        )
                        await asyncio.to_thread(
                            extract_audio_window, source, audio_path, audio_window
                        )
                        transcription = await self.scheduler.submit(
                            self._transcribe,
                            audio_path,
                            options.transcription_language,
                            kind="ingestion",
                        )
                        transcription_language = transcription.get("language")
                        for index, segment in enumerate(
                            transcription.get("segments", [])
                        ):
                            text = str(segment.get("text", "")).strip()
                            if not text:
                                continue
                            words = segment.get("words") or []
                            if words:
                                relative_start = min(
                                    float(word["start"]) for word in words
                                )
                                relative_end = max(float(word["end"]) for word in words)
                            else:
                                relative_start = max(
                                    0.0, float(segment.get("start", 0))
                                )
                                relative_end = max(
                                    relative_start,
                                    float(segment.get("end", relative_start)),
                                )
                            start = min(
                                audio_window.end,
                                audio_window.start + relative_start,
                            )
                            end = min(
                                audio_window.end,
                                max(start, audio_window.start + relative_end),
                            )
                            text_blocks.append(
                                TextBlock(
                                    text,
                                    None,
                                    {
                                        "language": transcription_language,
                                        "window_start": audio_window.start,
                                        "whisper_segment": index,
                                    },
                                    kind="transcript",
                                    time_start=start,
                                    time_end=end,
                                )
                            )
                            transcript_count += 1
                        audio_vector = await self.scheduler.submit(
                            self._embed_audio, audio_path, kind="ingestion"
                        )
                        media_records.append(
                            {
                                "kind": "audio",
                                "start": audio_window.start,
                                "end": audio_window.end,
                                "vector": audio_vector,
                                "metadata": {
                                    "preset": preset,
                                    "sample_rate": 16000,
                                    "channels": 1,
                                    "profile_window_start": window.start,
                                    "profile_window_end": window.end,
                                    "effective_window_seconds": min(
                                        MAX_AUDIO_WINDOW_SECONDS,
                                        sample["window_seconds"],
                                    ),
                                    "transcript_segments": len(
                                        transcription.get("segments", [])
                                    ),
                                },
                            }
                        )
                        audio_window_count += 1
                        audio_path.unlink(missing_ok=True)

                if is_video_asset and probe.has_video:
                    frame_dir = temp / f"frames-{ordinal:06d}"
                    decoded = await asyncio.to_thread(
                        extract_video_frames,
                        source,
                        frame_dir,
                        window,
                        sample["video_fps"],
                    )
                    from PIL import Image

                    images = [Image.open(path).convert("RGB") for path in decoded.paths]
                    try:
                        for image, path, timestamp in zip(
                            images, decoded.paths, decoded.timestamps
                        ):
                            encoded = await asyncio.to_thread(
                                self._encode_frame_png, image
                            )
                            ocr = await asyncio.to_thread(
                                self._ocr_bytes, encoded, options.ocr_languages
                            )
                            text = ocr["text"].strip()
                            if text:
                                end = min(
                                    window.end,
                                    timestamp + 1.0 / decoded.effective_fps,
                                )
                                prior_index = ocr_seen.get(text)
                                if prior_index is not None:
                                    prior = text_blocks[prior_index]
                                    if (
                                        prior.time_end is not None
                                        and timestamp <= prior.time_end + 1.5
                                    ):
                                        text_blocks[prior_index] = replace(
                                            prior,
                                            location={
                                                **prior.location,
                                                "last_timestamp": timestamp,
                                                "ocr_words_last": ocr["words"],
                                            },
                                            time_end=max(prior.time_end, end),
                                        )
                                    else:
                                        prior_index = None
                                if prior_index is None:
                                    ocr_seen[text] = len(text_blocks)
                                    text_blocks.append(
                                        TextBlock(
                                            text,
                                            None,
                                            {
                                                "timestamp": timestamp,
                                                "ocr_words": ocr["words"],
                                                "frame": path.name,
                                            },
                                            kind="ocr",
                                            time_start=timestamp,
                                            time_end=end,
                                        )
                                    )
                        if images:
                            video_vector = await self.scheduler.submit(
                                self._embed_video, images, kind="ingestion"
                            )
                            media_records.append(
                                {
                                    "kind": "video",
                                    "start": window.start,
                                    "end": window.end,
                                    "vector": video_vector,
                                    "metadata": {
                                        "preset": preset,
                                        "requested_fps": sample["video_fps"],
                                        "effective_fps": decoded.effective_fps,
                                        "frame_timestamps": decoded.timestamps,
                                    },
                                }
                            )
                            frame_count += len(images)
                    finally:
                        for image in images:
                            image.close()
                        for path in decoded.paths:
                            path.unlink(missing_ok=True)
                        frame_dir.rmdir()

        versions = {
            "ffprobe": probe.ffprobe_version,
            "ffmpeg": await asyncio.to_thread(self._tool_version, "ffmpeg", "-version"),
            "media_preset": preset,
            "window_seconds": sample["window_seconds"],
            "overlap_seconds": sample["overlap_seconds"],
            "requested_video_fps": sample["video_fps"],
            "audio_windows": len(windows) if probe.has_audio else 0,
            "audio_subwindows": audio_window_count,
            "effective_audio_window_seconds": min(
                MAX_AUDIO_WINDOW_SECONDS, sample["window_seconds"]
            ),
            "video_frames": frame_count,
            "transcript_segments": transcript_count,
            "whisper_model": (
                self.settings.whisper_model_name if probe.has_audio else None
            ),
            "whisper_sha256": (
                "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9"
                if probe.has_audio
                else None
            ),
            "transcription_language": transcription_language,
            "audio_stream": "present" if probe.has_audio else "skipped:no_audio_stream",
            "video_stream": "present" if probe.has_video else "absent",
        }
        return text_blocks, media_records, versions

    @staticmethod
    def _encode_frame_png(image: Any) -> bytes:
        from io import BytesIO

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    @staticmethod
    def _ocr_bytes(content: bytes, languages: str) -> dict[str, Any]:
        from search_anything.ingestion import ocr_image

        result = ocr_image(content, languages)
        return {"text": result.text, "words": result.words}

    async def index_generation(self, job: LeasedJob) -> None:
        if job.asset_id is None or job.generation_id is None:
            raise ValueError("index job is missing an asset or generation")
        async with self.session_factory() as session:
            asset = await session.get(Asset, job.asset_id)
            generation = await session.get(ProcessingGeneration, job.generation_id)
            if asset is None or generation is None or asset.state == "deleting":
                return
            key = asset.storage_key
            filename = asset.filename
            content_type = asset.content_type
            byte_size = asset.byte_size
            generation_options = IngestionOptions.model_validate(
                generation.profile_snapshot
            )

        is_av = content_type.startswith(("audio/", "video/"))
        media_records: list[dict[str, Any]] = []
        duration_seconds: float | None = None
        extractor_versions: dict[str, Any] = {}
        if is_av:
            with tempfile.TemporaryDirectory(prefix="search-anything-index-") as temp:
                source = Path(temp) / "original"
                await self._copy_object_to_path(key, source)
                blocks, media_records, extractor_versions = await self._index_av_file(
                    source, content_type, generation_options
                )
                duration_seconds = (
                    await asyncio.to_thread(probe_media, source)
                ).duration_seconds
            image = None
            extracted_pages = None
        else:
            if byte_size > MAX_DOCUMENT_BYTES:
                raise ValueError(
                    f"document exceeds the {MAX_DOCUMENT_BYTES}-byte extraction limit"
                )
            stored = await self.storage.get_object(key)
            try:
                content = await asyncio.to_thread(stored.body.read)
            finally:
                await asyncio.to_thread(stored.body.close)
            blocks, image, extracted_pages = await asyncio.to_thread(
                extract_document,
                filename,
                content_type,
                content,
                generation_options.ocr_languages,
            )
        chunks = await self.scheduler.submit(
            self._plan_chunks,
            blocks,
            filename,
            generation_options,
            kind="ingestion",
        )
        texts = [
            document_embedding_text(
                chunk.title,
                "\n".join(part for part in (chunk.heading, chunk.text) if part),
            )
            for chunk in chunks
        ]
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self.settings.embedding_batch_size):
            vectors.extend(
                await self.scheduler.submit(
                    self._embed_text_batch,
                    texts[offset : offset + self.settings.embedding_batch_size],
                    kind="ingestion",
                )
            )
        image_vector = (
            await self.scheduler.submit(self._embed_image, image, kind="ingestion")
            if image is not None
            else None
        )
        extractor_versions.update(
            {
                "text_extractor": "local-structure-v1",
                "embedding_model": MODEL_ID,
                "embedding_revision": MODEL_REVISION,
                "embedding_dimensions": DIMENSIONS,
            }
        )
        if image is not None or any(chunk.kind == "ocr" for chunk in chunks):
            extractor_versions["tesseract"] = await asyncio.to_thread(
                self._tool_version, "tesseract", "--version"
            )
        if image is not None:
            image.close()
        async with self.session_factory() as session:
            async with session.begin():
                current_asset = await session.scalar(
                    select(Asset).where(Asset.id == job.asset_id).with_for_update()
                )
                current_job = await session.scalar(
                    select(IngestionJob)
                    .where(
                        IngestionJob.id == job.id,
                        IngestionJob.status == "running",
                        IngestionJob.lease_token == job.lease_token,
                        IngestionJob.lease_expires_at > datetime.now(timezone.utc),
                        IngestionJob.cancellation_requested.is_(False),
                    )
                    .with_for_update()
                )
                current_generation = await session.scalar(
                    select(ProcessingGeneration)
                    .where(ProcessingGeneration.id == job.generation_id)
                    .with_for_update()
                )
                if (
                    current_job is None
                    or current_asset is None
                    or current_generation is None
                ):
                    raise LeaseLost(f"index job {job.id} was reclaimed")
                if (
                    current_asset.state == "deleting"
                    or current_job.cancellation_requested
                ):
                    return
                await session.execute(
                    delete(Representation).where(
                        Representation.generation_id == job.generation_id
                    )
                )
                await session.execute(
                    delete(Segment).where(Segment.generation_id == job.generation_id)
                )
                for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors)):
                    segment_id = uuid4()
                    segment = Segment(
                        id=segment_id,
                        generation_id=job.generation_id,
                        ordinal=ordinal,
                        content_type=chunk.kind,
                        body=chunk.text,
                        source_location={
                            **chunk.location,
                            "heading": chunk.heading,
                            "token_count": chunk.token_count,
                        },
                        source_start=chunk.source_start,
                        source_end=chunk.source_end,
                        time_start=chunk.time_start,
                        time_end=chunk.time_end,
                    )
                    representation = Representation(
                        id=uuid4(),
                        generation_id=job.generation_id,
                        segment_id=segment_id,
                        kind=(
                            chunk.kind
                            if chunk.kind in {"ocr", "transcript"}
                            else "text"
                        ),
                        text_content=chunk.text,
                        detected_language=chunk.location.get("language"),
                        metadata_json={
                            "heading": chunk.heading,
                            "source_location": chunk.location,
                        },
                    )
                    session.add_all(
                        [
                            segment,
                            representation,
                            Embedding(
                                id=uuid4(),
                                representation_id=representation.id,
                                model_id=MODEL_ID,
                                model_revision=MODEL_REVISION,
                                dimensions=DIMENSIONS,
                                vector=vector,
                            ),
                        ]
                    )
                if image_vector is not None:
                    image_representation = Representation(
                        id=uuid4(),
                        generation_id=job.generation_id,
                        kind="image",
                        text_content=None,
                        metadata_json={
                            "filename": filename,
                            "content_type": content_type,
                        },
                    )
                    session.add_all(
                        [
                            image_representation,
                            Embedding(
                                id=uuid4(),
                                representation_id=image_representation.id,
                                model_id=MODEL_ID,
                                model_revision=MODEL_REVISION,
                                dimensions=DIMENSIONS,
                                vector=image_vector,
                            ),
                        ]
                    )
                next_ordinal = len(chunks)
                for media_record in media_records:
                    segment_id = uuid4()
                    segment = Segment(
                        id=segment_id,
                        generation_id=job.generation_id,
                        ordinal=next_ordinal,
                        content_type=media_record["kind"],
                        body=None,
                        source_location=media_record["metadata"],
                        time_start=media_record["start"],
                        time_end=media_record["end"],
                    )
                    representation = Representation(
                        id=uuid4(),
                        generation_id=job.generation_id,
                        segment_id=segment_id,
                        kind=media_record["kind"],
                        text_content=None,
                        metadata_json=media_record["metadata"],
                    )
                    session.add_all(
                        [
                            segment,
                            representation,
                            Embedding(
                                id=uuid4(),
                                representation_id=representation.id,
                                model_id=MODEL_ID,
                                model_revision=MODEL_REVISION,
                                dimensions=DIMENSIONS,
                                vector=media_record["vector"],
                            ),
                        ]
                    )
                    next_ordinal += 1
                current_generation.extractor_versions = {
                    **current_generation.extractor_versions,
                    **extractor_versions,
                }
                current_generation.state = "complete"
                if extracted_pages is not None:
                    current_asset.page_count = extracted_pages
                if duration_seconds is not None:
                    current_asset.duration_seconds = duration_seconds
                await activate_generation(session, job.asset_id, job.generation_id, job)
                current_job.status = "succeeded"
                current_job.progress = 1.0
                current_job.lease_owner = None
                current_job.lease_token = None
                current_job.lease_expires_at = None
                current_job.heartbeat_at = datetime.now(timezone.utc)

    @staticmethod
    def _tool_version(executable: str, *args: str) -> str:
        result = subprocess.run(
            [executable, *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.splitlines()[0]

    async def cleanup_asset(self, job: LeasedJob) -> None:
        asset_id = job.asset_id
        if asset_id is None:
            asset_id = UUID(str(job.payload["asset_id"]))
        async with self.session_factory() as session:
            asset = await session.get(Asset, asset_id)
            if asset is None:
                try:
                    await complete_job(self.session_factory, job)
                except LeaseLost:
                    pass
                return
            keys = [asset.storage_key]
            artifact_keys = await session.scalars(
                select(DerivedArtifact.storage_key)
                .join(ProcessingGeneration)
                .where(ProcessingGeneration.asset_id == asset_id)
            )
            keys.extend(artifact_keys.all())
        for key in keys:
            await self.storage.delete_object(key)
        async with self.session_factory() as session:
            async with session.begin():
                current_job = await session.scalar(
                    select(IngestionJob)
                    .where(
                        IngestionJob.id == job.id,
                        IngestionJob.lease_token == job.lease_token,
                        IngestionJob.status == "running",
                        IngestionJob.lease_expires_at > datetime.now(timezone.utc),
                        IngestionJob.cancellation_requested.is_(False),
                    )
                    .with_for_update()
                )
                asset = await session.get(Asset, asset_id)
                if current_job is None:
                    raise LeaseLost(f"cleanup job {job.id} was reclaimed")
                if asset is not None:
                    await session.delete(asset)


async def run_worker(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    engine = make_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    worker = Worker(settings, session_factory, S3ObjectStorage(settings))
    try:
        await worker.run()
    finally:
        await engine.dispose()
