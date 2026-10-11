"""Durable search contract against an explicitly selected, isolated Postgres DB.

No model downloads or external object storage are required.
"""

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from search_anything.api import create_app
from search_anything.db import make_engine
from search_anything.events import WorkWakeup, notify_work
from search_anything.jobs import LeaseLost, claim_job, renew_lease
from search_anything.models import (
    Asset,
    IngestionJob,
    ProcessingGeneration,
    Representation,
    Workspace,
)
from search_anything.settings import Settings
from search_anything.storage import ObjectRead
from search_anything.worker import Worker

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.getenv("SEARCH_QUEUE_TEST_DATABASE_URL"),
        reason="requires isolated Postgres test database",
    ),
]


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    async def put_file(self, key, fileobj, content_type, content_hash):
        self.objects[key] = fileobj.read()

    async def get_object(self, key):
        raw = self.objects[key]
        return ObjectRead(
            BytesIO(raw), len(raw), "application/octet-stream", None, False
        )

    async def delete_object(self, key):
        self.objects.pop(key, None)


async def test_durable_search_contract_and_recovery(monkeypatch):
    database_url = os.environ["SEARCH_QUEUE_TEST_DATABASE_URL"]
    target = make_url(database_url)
    assert target.drivername == "postgresql+asyncpg"
    assert target.database.endswith("_test")
    assert target.database != make_url(Settings().database_url).database
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        default_workspace_id=uuid4(),
        job_poll_seconds=0.1,
    )
    engine = make_engine(settings)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    storage = MemoryStorage()
    worker = Worker(settings, sessions, storage)
    worker._embed_query_text = lambda text: [0.0] * 768
    other = uuid4()
    workspace = settings.default_workspace_id
    app = create_app(settings, session_factory=sessions, storage=storage)
    try:
        async with sessions() as session:
            session.add_all(
                [
                    Workspace(id=workspace, name="queue-test"),
                    Workspace(id=other, name="other"),
                ]
            )
            await session.commit()
        asset_ids = {}
        async with sessions() as session:
            for owner in (workspace, other):
                asset = Asset(
                    id=uuid4(),
                    workspace_id=owner,
                    filename="moon.txt",
                    normalized_filename="moon.txt",
                    content_type="text/plain",
                    byte_size=4,
                    content_hash="0" * 64,
                    storage_key=f"fixture/{owner}",
                    state="ready",
                )
                session.add(asset)
                await session.flush()
                generation = ProcessingGeneration(
                    id=uuid4(), asset_id=asset.id, state="active", profile_snapshot={}
                )
                session.add(generation)
                await session.flush()
                session.add(
                    Representation(
                        id=uuid4(),
                        generation_id=generation.id,
                        kind="text",
                        text_content="moon",
                        metadata_json={},
                    )
                )
                asset.active_generation_id = generation.id
                asset_ids[owner] = str(asset.id)
            await session.commit()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Establish LISTEN before producing work. NOTIFY follows commit.
            async with WorkWakeup(database_url) as wakeup:
                for _ in range(100):
                    if getattr(wakeup, "connected", False):
                        break
                    await asyncio.sleep(0.01)
                assert wakeup.connected
                async with sessions() as session:
                    await notify_work(session)
                    await session.rollback()
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(wakeup.event.wait(), 0.05)
                submitted = await client.post(
                    "/api/search", json={"query": "moon", "mode": "keyword"}
                )
                assert submitted.status_code == 202
                await asyncio.wait_for(wakeup.event.wait(), 2)
                ident = submitted.json()["id"]
            before = await client.get(f"/api/search/jobs/{ident}")
            assert before.json()["status"] == "queued"
            assert before.json()["result"] is None
            assert (
                await client.get(
                    f"/api/search/jobs/{ident}", params={"workspace_id": str(other)}
                )
            ).status_code == 404
            # Only one worker can own the claim; an expired owner cannot publish.
            old = await claim_job(sessions, "old", 60, stages=("search",))
            assert old.id == UUID(ident)
            assert await claim_job(sessions, "second", 60, stages=("search",)) is None
            async with sessions() as session:
                await session.execute(
                    update(IngestionJob)
                    .where(IngestionJob.id == old.id)
                    .values(
                        lease_expires_at=datetime.now(timezone.utc)
                        - timedelta(seconds=1)
                    )
                )
                await session.commit()
            new = await claim_job(sessions, "new", 60, stages=("search",))
            assert new.id == old.id and new.lease_token != old.lease_token
            with pytest.raises(LeaseLost):
                await renew_lease(sessions, old, 60)
            await renew_lease(sessions, new, 60)
            with pytest.raises(LeaseLost):
                await worker.search_job(old)
            await worker.search_job(new)
            result = (await client.get(f"/api/search/jobs/{ident}")).json()
            assert result["status"] == "succeeded"
            assert result["result"]["query"] == "moon"
            assert [hit["asset_id"] for hit in result["result"]["results"]] == [
                asset_ids[workspace]
            ]
            # Binary data travels through object storage, not the jobs row.
            prepared = {"vector": None, "transcript": "moon", "pooled_modalities": []}
            worker._prepare_media_query = AsyncMock(return_value=prepared)
            media = await client.post(
                "/api/search/media",
                data={"mode": "keyword"},
                files={"file": ("sample.wav", b"media", "audio/wav")},
            )
            assert media.status_code == 202
            media_id = UUID(media.json()["id"])
            async with sessions() as session:
                row = await session.get(IngestionJob, media_id)
                key = row.payload["storage_key"]
                assert "content_base64" not in row.payload
                assert storage.objects[key] == b"media"
            assert await worker.run_once(("search",))
            worker._prepare_media_query.assert_awaited_once_with(
                b"media", "audio/wav", include_embeddings=False, query_text=""
            )
            assert (await client.get(f"/api/search/jobs/{media_id}")).json()["result"][
                "source_filename"
            ] == "sample.wav"
            await worker.cleanup_query_inputs()
            assert key not in storage.objects
            # Infrastructure failures remain retryable; a subsequent claim
            # uses the same durable request and publishes a successful result.
            attempts = 0

            def flaky_embedding(_):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("temporary inference failure")
                return [0.0] * 768

            worker._embed_query_text = flaky_embedding
            transient = await client.post(
                "/api/search",
                json={
                    "query": "moon",
                    "mode": "semantic",
                    "asset_ids": [asset_ids[workspace]],
                },
            )
            transient_id = UUID(transient.json()["id"])
            assert await worker.run_once(("search",))
            assert (await client.get(f"/api/search/jobs/{transient_id}")).json()[
                "status"
            ] == "retry"
            async with sessions() as session:
                await session.execute(
                    update(IngestionJob)
                    .where(IngestionJob.id == transient_id)
                    .values(available_at=datetime.now(timezone.utc))
                )
                await session.commit()
            assert await worker.run_once(("search",))
            assert (await client.get(f"/api/search/jobs/{transient_id}")).json()[
                "status"
            ] == "succeeded"
            # Invalid inputs fail immediately and expose a durable error.
            worker._embed_query_text = lambda _: (_ for _ in ()).throw(
                ValueError("bad query")
            )
            invalid = await client.post("/api/search", json={"query": "invalid"})
            assert await worker.run_once(("search",))
            failed = (
                await client.get(f"/api/search/jobs/{invalid.json()['id']}")
            ).json()
            assert (
                failed["status"] == "failed"
                and failed["error"]["message"] == "bad query"
            )
            # Separate query loop continues while ingestion is blocked. Exercise
            # polling fallback by making the notification connection unavailable.
            monkeypatch.setattr(
                "search_anything.events.connect_listener",
                AsyncMock(side_effect=OSError("listener unavailable")),
            )
            started, release = asyncio.Event(), asyncio.Event()

            async def ingestion(_):
                started.set()
                await release.wait()

            worker.handlers["probe"] = ingestion
            async with sessions() as session:
                session.add(
                    IngestionJob(
                        id=uuid4(),
                        stage="probe",
                        payload={},
                        idempotency_key=f"held:{workspace}",
                    )
                )
                await session.commit()
            running = asyncio.create_task(worker.run())
            try:
                await asyncio.wait_for(started.wait(), 2)
                pending = await client.post(
                    "/api/search", json={"query": "while indexing", "mode": "keyword"}
                )
                for _ in range(100):
                    polled = (
                        await client.get(f"/api/search/jobs/{pending.json()['id']}")
                    ).json()
                    if polled["status"] == "succeeded":
                        break
                    await asyncio.sleep(0.02)
                assert polled["status"] == "succeeded"
                assert not release.is_set()
            finally:
                release.set()
                running.cancel()
                with suppress(asyncio.CancelledError):
                    await running
            async with sessions() as session:
                await session.execute(
                    update(IngestionJob)
                    .where(IngestionJob.workspace_id == workspace)
                    .values(updated_at=datetime.now(timezone.utc) - timedelta(days=2))
                )
                await session.commit()
            await worker.cleanup_query_inputs()
            assert (await client.get(f"/api/search/jobs/{ident}")).status_code == 404
    finally:
        await worker.scheduler.close()
        async with sessions() as session:
            await session.execute(
                delete(IngestionJob).where(
                    IngestionJob.idempotency_key == f"held:{workspace}"
                )
            )
            await session.execute(
                delete(Workspace).where(Workspace.id.in_([workspace, other]))
            )
            await session.commit()
        await engine.dispose()
