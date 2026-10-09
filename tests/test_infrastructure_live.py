"""Run against the real Compose Postgres and RustFS services."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from io import BytesIO
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
from PIL import Image, ImageDraw
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from search_anything.api import create_app
from search_anything.db import make_engine
from search_anything.embeddings import ContextLimitError
from search_anything.ingestion import TextBlock, chunk_blocks
from search_anything.jobs import (
    LeaseLost,
    claim_job,
    complete_job,
)
from search_anything.models import (
    Asset,
    Embedding,
    IngestionJob,
    IngestionProfile,
    ProcessingGeneration,
    Representation,
    Segment,
)
from search_anything.settings import Settings
from search_anything.storage import S3ObjectStorage
from search_anything.worker import Worker

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("SEARCH_INTEGRATION_TESTS") != "1",
        reason="requires live Postgres and RustFS from docker compose",
    ),
    pytest.mark.asyncio,
]


async def test_live_upload_ranges_presigned_jobs_generation_and_cleanup(
    tmp_path: Path,
) -> None:
    settings = Settings(
        default_workspace_id=uuid4(),
        default_workspace_name="Integration",
        model_socket_path=Path("/tmp") / f"sa-{uuid4().hex[:8]}" / "model.sock",
    )
    engine = make_engine(settings)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    storage = S3ObjectStorage(settings)
    app = create_app(settings, session_factory=sessions, storage=storage)
    transport = httpx.ASGITransport(app=app)

    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                ready = await client.get("/health/ready")
                assert ready.status_code == 200
                assert ready.json() == {
                    "status": "ready",
                    "database": "ready",
                    "storage": "ready",
                }

                body = b"the range response must be exact"
                responses = await asyncio.gather(
                    *(
                        client.post(
                            "/api/assets",
                            files={
                                "file": (
                                    f"range-fixture-{number}.txt",
                                    body,
                                    "text/plain",
                                )
                            },
                        )
                        for number in range(2)
                    )
                )
                assert [response.status_code for response in responses] == [
                    201,
                    201,
                ], [response.text for response in responses]
                result, concurrent_result = [response.json() for response in responses]
                asset_id = UUID(result["asset"]["id"])
                concurrent_asset_id = UUID(concurrent_result["asset"]["id"])
                generation_id = UUID(result["generation_id"])
                assert concurrent_asset_id != asset_id
                async with sessions() as session:
                    profile_count = await session.scalar(
                        select(func.count(IngestionProfile.id)).where(
                            IngestionProfile.workspace_id
                            == settings.default_workspace_id
                        )
                    )
                    assert profile_count == 1
                initial_status = await client.get(f"/api/assets/{asset_id}/status")
                assert initial_status.status_code == 200
                initial_status_body = initial_status.json()
                assert initial_status_body["current_generation_id"] == str(
                    generation_id
                )
                assert (
                    initial_status_body["generations"][0]["jobs"][0]["stage"] == "probe"
                )
                profiles = await client.get("/api/profiles")
                assert profiles.status_code == 200
                assert [
                    (profile["name"], profile["revision"])
                    for profile in profiles.json()
                ] == [("automatic", 1)]
                profile_options = {
                    "strategy": "automatic",
                    "version": 1,
                    "media_preset": "general_video",
                    "media_window_seconds": 12,
                    "media_overlap_seconds": 2,
                    "video_sampling_fps": 3,
                    "transcription_language": "en",
                    "text_chunk_tokens": 256,
                    "text_overlap_tokens": 16,
                    "ocr_languages": "eng",
                }
                saved_profile = await client.put(
                    "/api/profiles/automatic", json={"options": profile_options}
                )
                assert saved_profile.status_code == 200, saved_profile.text
                assert saved_profile.json()["revision"] == 2
                profile_options["text_chunk_tokens"] = 512
                latest_profile = await client.put(
                    "/api/profiles/automatic", json={"options": profile_options}
                )
                assert latest_profile.status_code == 200, latest_profile.text
                assert latest_profile.json()["revision"] == 3

                full = await client.get(f"/api/assets/{asset_id}/content")
                assert full.status_code == 200
                assert full.content == body
                assert full.headers["accept-ranges"] == "bytes"

                ranged = await client.get(
                    f"/api/assets/{asset_id}/content",
                    headers={"Range": "bytes=4-11"},
                )
                assert ranged.status_code == 206
                assert ranged.content == body[4:12]
                assert ranged.headers["content-range"] == f"bytes 4-11/{len(body)}"

                rejected = await client.get(
                    f"/api/assets/{asset_id}/content",
                    headers={"Range": "bytes=999-"},
                )
                assert rejected.status_code == 416
                assert rejected.headers["content-range"] == f"bytes */{len(body)}"

                signed = await client.get(f"/api/assets/{asset_id}/presigned")
                assert signed.status_code == 200
                async with httpx.AsyncClient(timeout=10) as signed_client:
                    signed_content = await signed_client.get(signed.json()["url"])
                assert signed_content.status_code == 200
                assert signed_content.content == body

                # A second process takes an expired lease with a fresh fencing token.
                recovery_id = uuid4()
                async with sessions() as session:
                    session.add(
                        IngestionJob(
                            id=recovery_id,
                            stage="probe",
                            status="queued",
                            priority=-10,
                            payload={},
                            idempotency_key=f"recovery:{recovery_id}",
                            max_attempts=3,
                        )
                    )
                    await session.commit()
                first = await claim_job(sessions, "worker-a", lease_seconds=30)
                assert first is not None and first.id == recovery_id
                async with sessions() as session:
                    await session.execute(
                        update(IngestionJob)
                        .where(IngestionJob.id == recovery_id)
                        .values(
                            lease_expires_at=datetime.now(timezone.utc)
                            - timedelta(seconds=1)
                        )
                    )
                    await session.commit()
                recovered = await claim_job(sessions, "worker-b", lease_seconds=30)
                assert recovered is not None and recovered.id == recovery_id
                assert recovered.lease_token != first.lease_token
                with pytest.raises(LeaseLost):
                    await complete_job(sessions, first)
                await complete_job(sessions, recovered)

                image = Image.new("RGB", (640, 240), "white")
                ImageDraw.Draw(image).text((20, 40), "FIRE TRUCK", fill="black")
                image_bytes = BytesIO()
                image.save(image_bytes, format="PNG")
                image_path = tmp_path / "fire-truck.png"
                image.save(image_path)
                image_response = await client.post(
                    "/api/assets",
                    files={
                        "file": ("fire-truck.png", image_bytes.getvalue(), "image/png")
                    },
                )
                assert image_response.status_code == 201, image_response.text
                image_result = image_response.json()
                image_asset_id = UUID(image_result["asset"]["id"])
                image_generation_id = UUID(image_result["generation_id"])

                speech_path = tmp_path / "spoken-fixture.aiff"
                subprocess.run(
                    [
                        "/usr/bin/say",
                        "-o",
                        str(speech_path),
                        "The red truck is parked near the station.",
                    ],
                    check=True,
                    timeout=30,
                )
                late_speech_path = tmp_path / "late-spoken-fixture.aiff"
                subprocess.run(
                    [
                        "/usr/bin/say",
                        "-o",
                        str(late_speech_path),
                        "A blue bicycle arrives at midnight.",
                    ],
                    check=True,
                    timeout=30,
                )
                first_wav = tmp_path / "first.wav"
                late_wav = tmp_path / "late.wav"
                silence_wav = tmp_path / "silence.wav"
                for input_path, output_path in (
                    (speech_path, first_wav),
                    (late_speech_path, late_wav),
                ):
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-i",
                            str(input_path),
                            "-ac",
                            "1",
                            "-ar",
                            "16000",
                            "-c:a",
                            "pcm_s16le",
                            "-y",
                            str(output_path),
                        ],
                        check=True,
                        timeout=30,
                    )
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=16000:cl=mono",
                        "-t",
                        "31",
                        "-c:a",
                        "pcm_s16le",
                        "-y",
                        str(silence_wav),
                    ],
                    check=True,
                    timeout=30,
                )
                concat_list = tmp_path / "audio-files.txt"
                concat_list.write_text(
                    "".join(
                        f"file '{path}'\n"
                        for path in (first_wav, silence_wav, late_wav)
                    )
                )
                long_audio_path = tmp_path / "spoken-after-30-seconds.wav"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        str(concat_list),
                        "-c",
                        "copy",
                        "-y",
                        str(long_audio_path),
                    ],
                    check=True,
                    timeout=30,
                )
                audio_response = await client.post(
                    "/api/assets",
                    files={
                        "file": (
                            "spoken-fixture.wav",
                            long_audio_path.read_bytes(),
                            "audio/wav",
                        )
                    },
                )
                assert audio_response.status_code == 201, audio_response.text
                audio_result = audio_response.json()
                audio_asset_id = UUID(audio_result["asset"]["id"])
                audio_generation_id = UUID(audio_result["generation_id"])

                video_path = tmp_path / "silent-video.mp4"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-loop",
                        "1",
                        "-framerate",
                        "4",
                        "-i",
                        str(image_path),
                        "-t",
                        "3",
                        "-vf",
                        "fps=4",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-y",
                        str(video_path),
                    ],
                    check=True,
                    timeout=30,
                )
                video_response = await client.post(
                    "/api/assets",
                    files={
                        "file": (
                            "silent-video.mp4",
                            video_path.read_bytes(),
                            "video/mp4",
                        )
                    },
                )
                assert video_response.status_code == 201, video_response.text
                video_result = video_response.json()
                video_asset_id = UUID(video_result["asset"]["id"])
                video_generation_id = UUID(video_result["generation_id"])

                worker = Worker(settings, sessions, storage)
                asset_ids = (
                    asset_id,
                    concurrent_asset_id,
                    image_asset_id,
                    audio_asset_id,
                    video_asset_id,
                )
                for _ in range(30):
                    async with sessions() as session:
                        generations = (
                            await session.scalars(
                                select(ProcessingGeneration).where(
                                    ProcessingGeneration.asset_id.in_(asset_ids)
                                )
                            )
                        ).all()
                        all_active = len(generations) == 5 and all(
                            generation.state == "active" for generation in generations
                        )
                    if all_active:
                        break
                    assert await worker.run_once()
                assert all_active, "worker did not index all local fixtures"
                async with sessions() as session:
                    asset = await session.get(Asset, asset_id)
                    assert asset is not None
                    assert asset.active_generation_id == generation_id
                    text_embeddings = await session.scalar(
                        select(func.count(Embedding.id))
                        .join(Representation)
                        .where(Representation.generation_id == generation_id)
                    )
                    assert text_embeddings > 0
                    vector = await session.scalar(
                        select(Embedding.vector)
                        .join(Representation)
                        .where(Representation.generation_id == generation_id)
                        .limit(1)
                    )
                    assert (
                        abs(sum(value * value for value in vector) ** 0.5 - 1.0) < 0.02
                    )
                    image_embeddings = await session.scalar(
                        select(func.count(Embedding.id))
                        .join(Representation)
                        .where(Representation.generation_id == image_generation_id)
                    )
                    assert image_embeddings >= 2
                    assert (
                        await session.scalar(
                            select(func.count(Representation.id)).where(
                                Representation.generation_id == image_generation_id,
                                Representation.kind == "combined",
                            )
                        )
                        == 0
                    )
                    ocr_text = await session.scalar(
                        select(Representation.text_content).where(
                            Representation.generation_id == image_generation_id,
                            Representation.kind == "ocr",
                        )
                    )
                    assert ocr_text and "FIRE" in ocr_text.upper()
                    audio_asset = await session.get(Asset, audio_asset_id)
                    video_asset = await session.get(Asset, video_asset_id)
                    assert audio_asset and audio_asset.duration_seconds is not None
                    assert video_asset and video_asset.duration_seconds is not None
                    transcripts = (
                        await session.scalars(
                            select(Representation.text_content).where(
                                Representation.generation_id == audio_generation_id,
                                Representation.kind == "transcript",
                            )
                        )
                    ).all()
                    joined_transcript = " ".join(transcripts).casefold()
                    assert "truck" in joined_transcript
                    assert "bicycle" in joined_transcript
                    transcript_segments = (
                        await session.scalars(
                            select(Segment)
                            .join(
                                Representation, Representation.segment_id == Segment.id
                            )
                            .where(
                                Representation.generation_id == audio_generation_id,
                                Representation.kind == "transcript",
                            )
                        )
                    ).all()
                    assert transcript_segments
                    assert all(
                        segment.time_start is not None
                        and segment.time_end > segment.time_start
                        for segment in transcript_segments
                    )
                    assert any(
                        segment.time_start > 30 for segment in transcript_segments
                    ), [
                        (segment.time_start, segment.body)
                        for segment in transcript_segments
                    ]
                    audio_representations = (
                        await session.scalars(
                            select(Representation).where(
                                Representation.generation_id == audio_generation_id,
                                Representation.kind == "audio",
                            )
                        )
                    ).all()
                    assert len(audio_representations) >= 2
                    video_representation = await session.scalar(
                        select(Representation).where(
                            Representation.generation_id == video_generation_id,
                            Representation.kind == "video",
                        )
                    )
                    assert video_representation is not None
                    timestamps = video_representation.metadata_json["frame_timestamps"]
                    assert len(timestamps) >= 2
                    assert timestamps[0] >= 0 and timestamps[-1] <= 3.05
                    assert any(
                        segment.content_type == "ocr" and segment.time_start is not None
                        for segment in await session.scalars(
                            select(Segment).where(
                                Segment.generation_id == video_generation_id
                            )
                        )
                    )
                    video_versions = (
                        await session.get(ProcessingGeneration, video_generation_id)
                    ).extractor_versions
                    assert video_versions["audio_stream"] == "skipped:no_audio_stream"
                assert worker._embedding_model is not None
                combined_options = {**profile_options, "combined_media_text": True}
                combined_profile = await client.put(
                    "/api/profiles/combined",
                    json={"options": combined_options},
                )
                assert combined_profile.status_code == 200, combined_profile.text
                combined_reprocess = await client.post(
                    f"/api/assets/{image_asset_id}/reprocess",
                    json={"profile_name": "combined"},
                )
                assert combined_reprocess.status_code == 202
                combined_generation_id = UUID(
                    combined_reprocess.json()["generation_id"]
                )
                for _ in range(3):
                    if not await worker.run_once():
                        break
                    async with sessions() as session:
                        combined_generation = await session.get(
                            ProcessingGeneration, combined_generation_id
                        )
                        if combined_generation.state == "active":
                            break
                async with sessions() as session:
                    combined_generation = await session.get(
                        ProcessingGeneration, combined_generation_id
                    )
                    assert combined_generation.state == "active"
                    assert combined_generation.profile_snapshot["combined_media_text"]
                    assert (
                        combined_generation.extractor_versions["index_duration_seconds"]
                        > 0
                    )
                    combined_representations = (
                        await session.scalars(
                            select(Representation).where(
                                Representation.generation_id == combined_generation_id,
                                Representation.kind == "combined",
                            )
                        )
                    ).all()
                    assert len(combined_representations) == 1
                    combined_embedding = await session.scalar(
                        select(Embedding).where(
                            Embedding.representation_id
                            == combined_representations[0].id
                        )
                    )
                    assert combined_embedding is not None
                    assert len(combined_embedding.vector) == 768
                combined_audio_reprocess = await client.post(
                    f"/api/assets/{audio_asset_id}/reprocess",
                    json={"profile_name": "combined"},
                )
                assert combined_audio_reprocess.status_code == 202
                combined_audio_generation_id = UUID(
                    combined_audio_reprocess.json()["generation_id"]
                )
                for _ in range(4):
                    if not await worker.run_once():
                        break
                    async with sessions() as session:
                        combined_audio_generation = await session.get(
                            ProcessingGeneration, combined_audio_generation_id
                        )
                        if combined_audio_generation.state == "active":
                            break
                async with sessions() as session:
                    combined_audio_generation = await session.get(
                        ProcessingGeneration, combined_audio_generation_id
                    )
                    assert combined_audio_generation.state == "active"
                    combined_audio_representations = (
                        await session.scalars(
                            select(Representation).where(
                                Representation.generation_id
                                == combined_audio_generation_id,
                                Representation.kind == "combined",
                            )
                        )
                    ).all()
                    assert combined_audio_representations
                    combined_audio_embedding = await session.scalar(
                        select(Embedding).where(
                            Embedding.representation_id
                            == combined_audio_representations[0].id
                        )
                    )
                    assert combined_audio_embedding is not None
                    audio_vector_norm = (
                        sum(value * value for value in combined_audio_embedding.vector)
                        ** 0.5
                    )
                    assert audio_vector_norm == pytest.approx(1.0, abs=1e-4)
                    combined_audio_segment = await session.get(
                        Segment, combined_audio_representations[0].segment_id
                    )
                    assert combined_audio_segment is not None
                    assert combined_audio_segment.time_start is not None
                    assert combined_audio_segment.time_end is not None
                    assert combined_audio_representations[0].metadata_json[
                        "modalities"
                    ] == ["audio", "transcript"]
                audio_generation_id = combined_audio_generation_id
                image_generation_id = combined_generation_id
                query_server = await worker._start_query_server()
                text_search = await client.post(
                    "/api/search",
                    json={"query": "fire truck", "mode": "hybrid", "limit": 10},
                )
                assert text_search.status_code == 200, text_search.text
                text_results = text_search.json()["results"]
                assert text_search.json()["representation_mode"] == "separate"
                assert all(
                    "combined" not in match["channel_evidence"]
                    for result in text_results
                    for match in result["matches"]
                )
                assert any(
                    representation["kind"] == "ocr"
                    and "fire" in (representation["text"] or "").casefold()
                    for result in text_results
                    for match in result["matches"]
                    for representation in match["representations"]
                )
                filtered_search = await client.post(
                    "/api/search",
                    json={
                        "query": "fire truck",
                        "mode": "keyword",
                        "content_types": ["image/png"],
                        "asset_ids": [str(image_asset_id)],
                    },
                )
                assert filtered_search.status_code == 200, filtered_search.text
                assert [
                    result["asset_id"] for result in filtered_search.json()["results"]
                ] == [str(image_asset_id)]
                channel_search = await client.post(
                    "/api/search",
                    json={
                        "query": "fire truck",
                        "mode": "semantic",
                        "weights": {
                            "text": 0,
                            "transcript": 0,
                            "ocr": 3,
                            "image": 0,
                            "audio": 0,
                            "video": 0,
                            "combined": 0,
                            "lexical": 0,
                            "identifier": 0,
                            "filename": 0,
                        },
                    },
                )
                assert channel_search.status_code == 200, channel_search.text
                assert any(
                    result["asset_id"] == str(image_asset_id)
                    for result in channel_search.json()["results"]
                )
                assert all(
                    set(match["channel_evidence"]) == {"ocr"}
                    for result in channel_search.json()["results"]
                    for match in result["matches"]
                )
                image_search = await client.post(
                    "/api/search/image",
                    files={"file": ("query.png", image_bytes.getvalue(), "image/png")},
                )
                assert image_search.status_code == 200, image_search.text
                assert any(
                    result["asset_id"] == str(image_asset_id)
                    for result in image_search.json()["results"]
                )
                combined_search = await client.post(
                    "/api/search",
                    json={
                        "query": "fire truck",
                        "mode": "semantic",
                        "asset_ids": [str(image_asset_id)],
                        "representation_mode": "combined",
                    },
                )
                assert combined_search.status_code == 200, combined_search.text
                assert combined_search.json()["results"]
                assert all(
                    set(match["channel_evidence"]) == {"combined"}
                    for result in combined_search.json()["results"]
                    for match in result["matches"]
                )
                media_search = await client.post(
                    "/api/search/media",
                    data={
                        "query": "blue bicycle",
                        "mode": "hybrid",
                        "asset_ids": json.dumps([str(audio_asset_id)]),
                    },
                    files={
                        "file": (
                            "query-audio.wav",
                            long_audio_path.read_bytes(),
                            "audio/wav",
                        )
                    },
                )
                assert media_search.status_code == 200, media_search.text
                media_query = media_search.json()
                assert "audio" in media_query["pooled_modalities"]
                assert "text" in media_query["pooled_modalities"]
                assert media_query["query_window_count"] <= 4
                assert media_query["query_duration_seconds"] <= 120
                assert media_query["covered_ranges_seconds"]["audio"][0][0] == 0
                assert (
                    media_query["covered_ranges_seconds"]["audio"][-1][1]
                    == media_query["query_duration_seconds"]
                )
                video_query = await client.post(
                    "/api/search/media",
                    files={
                        "file": (
                            "query-video.mp4",
                            video_path.read_bytes(),
                            "video/mp4",
                        )
                    },
                )
                assert video_query.status_code == 200, video_query.text
                video_query_body = video_query.json()
                assert "video" in video_query_body["pooled_modalities"]
                assert video_query_body["covered_ranges_seconds"]["audio"] == []
                assert (
                    video_query_body["covered_ranges_seconds"]["video"][-1][1]
                    == video_query_body["query_duration_seconds"]
                )
                overlong_audio = tmp_path / "overlong-query.wav"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=16000:cl=mono",
                        "-t",
                        "121",
                        "-c:a",
                        "pcm_s16le",
                        "-y",
                        str(overlong_audio),
                    ],
                    check=True,
                    timeout=30,
                )
                rejected_audio_query = await client.post(
                    "/api/search/media",
                    files={
                        "file": (
                            "overlong.wav",
                            overlong_audio.read_bytes(),
                            "audio/wav",
                        )
                    },
                )
                assert rejected_audio_query.status_code == 422
                assert "120 seconds" in rejected_audio_query.json()["detail"]
                overlong_video = tmp_path / "overlong-query.mp4"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=c=black:s=96x64:r=1:d=81",
                        "-an",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-y",
                        str(overlong_video),
                    ],
                    check=True,
                    timeout=30,
                )
                rejected_video_query = await client.post(
                    "/api/search/media",
                    files={
                        "file": (
                            "overlong.mp4",
                            overlong_video.read_bytes(),
                            "video/mp4",
                        )
                    },
                )
                assert rejected_video_query.status_code == 422
                assert "80 seconds" in rejected_video_query.json()["detail"]
                query_server.close()
                await query_server.wait_closed()
                settings.model_socket_path.unlink(missing_ok=True)
                settings.model_socket_path.parent.rmdir()
                with pytest.raises(ContextLimitError):
                    worker._embedding_model.embed_texts(["word " * 9000])
                with pytest.raises(ContextLimitError, match="audio windows"):
                    worker._embedding_model.embed_audio(long_audio_path)
                long_source = "A clear sentence ends here. " * 1800
                long_chunks = await worker.scheduler.submit(
                    chunk_blocks,
                    [
                        TextBlock(
                            long_source,
                            None,
                            {"offset_unit": "unicode_codepoint"},
                            0,
                            len(long_source),
                        )
                    ],
                    "long-fixture",
                    worker._embedding_model,
                    settings.chunk_target_tokens,
                    settings.chunk_overlap_tokens,
                    kind="ingestion",
                )
                assert len(long_chunks) > 1
                for chunk in long_chunks:
                    assert chunk.token_count <= settings.chunk_target_tokens
                    assert (
                        long_source[chunk.source_start : chunk.source_end] == chunk.text
                    )
                    assert chunk.text.endswith(".")

                cancelled_reprocess = await client.post(
                    f"/api/assets/{asset_id}/reprocess",
                    json={"profile_name": "automatic"},
                )
                assert cancelled_reprocess.status_code == 202
                cancelled_generation_id = UUID(
                    cancelled_reprocess.json()["generation_id"]
                )
                cancellation = await client.post(
                    f"/api/assets/{asset_id}/cancel",
                    json={"generation_id": str(cancelled_generation_id)},
                )
                assert cancellation.status_code == 202
                status_after_cancel = await client.get(f"/api/assets/{asset_id}/status")
                cancelled_status = status_after_cancel.json()
                assert cancelled_status["active_generation_id"] == str(generation_id)
                assert cancelled_status["state"] == "ready"
                assert cancelled_status["generations"][0]["state"] == "cancelled"
                assert (
                    cancelled_status["generations"][0]["jobs"][0]["status"]
                    == "cancelled"
                )

                reprocessed = await client.post(
                    f"/api/assets/{asset_id}/reprocess",
                    json={"profile_name": "automatic"},
                )
                assert reprocessed.status_code == 202, reprocessed.text
                assert reprocessed.json()["profile_revision"] == 3
                reprocessed_generation_id = UUID(reprocessed.json()["generation_id"])
                stale_cancel = await client.post(
                    f"/api/assets/{asset_id}/cancel",
                    json={"generation_id": str(cancelled_generation_id)},
                )
                assert stale_cancel.status_code == 202
                queued_status = await client.get(f"/api/assets/{asset_id}/status")
                assert queued_status.json()["state"] == "ready"
                assert queued_status.json()["current_generation_id"] == str(
                    reprocessed_generation_id
                )
                assert queued_status.json()["generations"][0]["state"] == "queued"
                assert await worker.run_once()
                async with sessions() as session:
                    asset = await session.get(Asset, asset_id)
                    assert asset is not None
                    assert asset.active_generation_id == generation_id
                    assert asset.state == "ready"
                assert await worker.run_once()
                async with sessions() as session:
                    asset = await session.get(Asset, asset_id)
                    previous = await session.get(ProcessingGeneration, generation_id)
                    replacement = await session.get(
                        ProcessingGeneration, reprocessed_generation_id
                    )
                    assert asset is not None
                    assert asset.active_generation_id == reprocessed_generation_id
                    assert previous is not None and previous.state == "superseded"
                    assert replacement is not None and replacement.state == "active"
                    assert replacement.profile_snapshot["revision"] == 3
                    assert replacement.profile_snapshot["text_chunk_tokens"] == 512

                unsupported_response = await client.post(
                    "/api/assets",
                    files={
                        "file": (
                            "unsupported.csv",
                            b"a,b\n1,2\n",
                            "text/csv",
                        )
                    },
                )
                assert unsupported_response.status_code == 201
                unsupported_result = unsupported_response.json()
                unsupported_asset_id = UUID(unsupported_result["asset"]["id"])
                unsupported_generation_id = UUID(unsupported_result["generation_id"])
                assert await worker.run_once()  # probe queues the unsupported index
                async with sessions() as session:
                    unsupported_index = await session.scalar(
                        select(IngestionJob).where(
                            IngestionJob.generation_id == unsupported_generation_id,
                            IngestionJob.stage == "index",
                        )
                    )
                    assert unsupported_index is not None
                    unsupported_index.max_attempts = 1
                    snapshot_before_retry = (
                        await session.get(
                            ProcessingGeneration, unsupported_generation_id
                        )
                    ).profile_snapshot
                    await session.commit()
                assert await worker.run_once()  # extraction fails on this format
                failed_status = await client.get(
                    f"/api/assets/{unsupported_asset_id}/status"
                )
                assert failed_status.status_code == 200
                failed_body = failed_status.json()
                assert failed_body["state"] == "failed"
                failed_generation = failed_body["generations"][0]
                assert failed_generation["state"] == "failed"
                failed_index = next(
                    job for job in failed_generation["jobs"] if job["stage"] == "index"
                )
                assert failed_index["status"] == "failed"
                assert failed_index["error_message"]
                retried = await client.post(f"/api/assets/{unsupported_asset_id}/retry")
                assert retried.status_code == 202, retried.text
                retry_status = await client.get(
                    f"/api/assets/{unsupported_asset_id}/status"
                )
                retried_generation = retry_status.json()["generations"][0]
                assert retry_status.json()["state"] == "queued"
                assert retried_generation["state"] == "queued"
                retry_job = next(
                    job for job in retried_generation["jobs"] if job["stage"] == "index"
                )
                assert retry_job["status"] == "retry"
                async with sessions() as session:
                    retry_generation = await session.get(
                        ProcessingGeneration, unsupported_generation_id
                    )
                    assert retry_generation.profile_snapshot == snapshot_before_retry
                cancelled_retry = await client.post(
                    f"/api/assets/{unsupported_asset_id}/cancel",
                    json={"generation_id": str(unsupported_generation_id)},
                )
                assert cancelled_retry.status_code == 202

                deleted = await client.delete(f"/api/assets/{asset_id}")
                assert deleted.status_code == 202
                concurrent_deleted = await client.delete(
                    f"/api/assets/{concurrent_asset_id}"
                )
                image_deleted = await client.delete(f"/api/assets/{image_asset_id}")
                unsupported_deleted = await client.delete(
                    f"/api/assets/{unsupported_asset_id}"
                )
                assert concurrent_deleted.status_code == 202
                assert image_deleted.status_code == 202
                assert unsupported_deleted.status_code == 202
                assert (
                    await client.get(f"/api/assets/{asset_id}/content")
                ).status_code == 404
                assert await worker.run_once()  # cleanup deletes storage and rows
                assert await worker.run_once()
                assert await worker.run_once()
                assert await worker.run_once()
                async with sessions() as session:
                    assert await session.get(Asset, asset_id) is None
                    assert await session.get(Asset, concurrent_asset_id) is None
                    assert await session.get(Asset, image_asset_id) is None
                    assert await session.get(Asset, unsupported_asset_id) is None
                after_delete_search = await client.post(
                    "/api/search",
                    json={"query": "FIRE TRUCK", "mode": "keyword"},
                )
                assert after_delete_search.status_code == 200
                assert all(
                    result["asset_id"] != str(image_asset_id)
                    for result in after_delete_search.json()["results"]
                )
                assert (await client.get(f"/api/assets/{asset_id}")).status_code == 404
                assert (
                    await client.get(f"/api/assets/{concurrent_asset_id}")
                ).status_code == 404
                await worker.scheduler.close()
    finally:
        await engine.dispose()
