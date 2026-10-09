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
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select, update
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
)
from search_anything.models import (
    Asset,
    DerivedArtifact,
    IngestionJob,
    ProcessingGeneration,
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
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}"
        self.handlers: dict[str, JobHandler] = {
            "probe": self.probe_asset,
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
            if await cancellation_requested(self.session_factory, job):
                await self.cancel_claim(job)
            elif job.stage != "cleanup":
                await complete_job(self.session_factory, job)
        except LeaseLost:
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
                    IngestionJob.lease_expires_at > datetime.now(timezone.utc),
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
                current_asset = await session.get(Asset, job.asset_id)
                generation = await session.get(ProcessingGeneration, job.generation_id)
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
                current_asset.state = "processing"
                if metadata:
                    duration = (metadata.get("format") or {}).get("duration")
                    if duration is not None:
                        current_asset.duration_seconds = float(duration)

    async def cleanup_asset(self, job: LeasedJob) -> None:
        asset_id = job.asset_id
        if asset_id is None:
            asset_id = UUID(str(job.payload["asset_id"]))
        async with self.session_factory() as session:
            asset = await session.get(Asset, asset_id)
            if asset is None:
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
