"""Run against the real Compose Postgres and RustFS services."""

from __future__ import annotations

import asyncio
import os
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


async def test_live_upload_ranges_presigned_jobs_generation_and_cleanup() -> None:
    settings = Settings(
        default_workspace_id=uuid4(), default_workspace_name="Integration"
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

                worker = Worker(settings, sessions, storage)
                asset_ids = (asset_id, concurrent_asset_id, image_asset_id)
                for _ in range(10):
                    async with sessions() as session:
                        generations = (
                            await session.scalars(
                                select(ProcessingGeneration).where(
                                    ProcessingGeneration.asset_id.in_(asset_ids)
                                )
                            )
                        ).all()
                        all_active = len(generations) == 3 and all(
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
                    ocr_text = await session.scalar(
                        select(Representation.text_content).where(
                            Representation.generation_id == image_generation_id,
                            Representation.kind == "ocr",
                        )
                    )
                    assert ocr_text and "FIRE" in ocr_text.upper()
                assert worker._embedding_model is not None
                with pytest.raises(ContextLimitError):
                    worker._embedding_model.embed_texts(["word " * 9000])
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

                reprocessed_generation_id = uuid4()
                async with sessions() as session:
                    profile = await session.scalar(
                        select(IngestionProfile).where(
                            IngestionProfile.workspace_id
                            == settings.default_workspace_id
                        )
                    )
                    assert profile is not None
                    session.add(
                        ProcessingGeneration(
                            id=reprocessed_generation_id,
                            asset_id=asset_id,
                            profile_snapshot={
                                "profile_id": str(profile.id),
                                "name": profile.name,
                                "revision": profile.revision,
                                **profile.config,
                            },
                            extractor_versions={},
                            state="queued",
                        )
                    )
                    await session.flush()
                    session.add(
                        IngestionJob(
                            id=uuid4(),
                            asset_id=asset_id,
                            generation_id=reprocessed_generation_id,
                            stage="probe",
                            status="queued",
                            priority=-20,
                            payload={
                                "asset_id": str(asset_id),
                                "generation_id": str(reprocessed_generation_id),
                            },
                            idempotency_key=(
                                f"generation:{reprocessed_generation_id}:probe"
                            ),
                            max_attempts=3,
                        )
                    )
                    await session.commit()
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

                deleted = await client.delete(f"/api/assets/{asset_id}")
                assert deleted.status_code == 202
                concurrent_deleted = await client.delete(
                    f"/api/assets/{concurrent_asset_id}"
                )
                image_deleted = await client.delete(f"/api/assets/{image_asset_id}")
                assert concurrent_deleted.status_code == 202
                assert image_deleted.status_code == 202
                assert (
                    await client.get(f"/api/assets/{asset_id}/content")
                ).status_code == 404
                assert await worker.run_once()  # cleanup deletes storage and rows
                assert await worker.run_once()
                assert await worker.run_once()
                async with sessions() as session:
                    assert await session.get(Asset, asset_id) is None
                    assert await session.get(Asset, concurrent_asset_id) is None
                    assert await session.get(Asset, image_asset_id) is None
                assert (await client.get(f"/api/assets/{asset_id}")).status_code == 404
                assert (
                    await client.get(f"/api/assets/{concurrent_asset_id}")
                ).status_code == 404
                await worker.scheduler.close()
    finally:
        await engine.dispose()
