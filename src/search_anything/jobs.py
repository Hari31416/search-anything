"""Durable Postgres queue with expiring leases and per-claim fencing tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from search_anything.models import (
    Asset,
    IngestionJob,
    ProcessingGeneration,
)


class LeaseLost(RuntimeError):
    """Raised when a stale worker tries to mutate a reclaimed job."""


@dataclass(frozen=True)
class LeasedJob:
    id: UUID
    asset_id: UUID | None
    generation_id: UUID | None
    stage: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    worker_id: str
    lease_token: UUID


async def claim_job(
    session_factory: async_sessionmaker,
    worker_id: str,
    lease_seconds: int,
) -> LeasedJob | None:
    now = datetime.now(timezone.utc)
    eligible = or_(
        and_(
            IngestionJob.status.in_(("queued", "retry")),
            IngestionJob.available_at <= now,
        ),
        and_(
            IngestionJob.status == "running",
            IngestionJob.lease_expires_at < now,
        ),
    )
    expired: tuple[UUID | None, UUID | None, UUID] | None = None
    leased: LeasedJob | None = None
    async with session_factory() as session:
        async with session.begin():
            job = await session.scalar(
                select(IngestionJob)
                .where(eligible, IngestionJob.cancellation_requested.is_(False))
                .order_by(
                    IngestionJob.priority,
                    IngestionJob.available_at,
                    IngestionJob.created_at,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                job.error_code = "lease_expired"
                job.error_message = (
                    "Job lease expired after the last permitted attempt."
                )
                job.lease_owner = None
                job.lease_token = None
                job.lease_expires_at = None
                expired = (job.asset_id, job.generation_id, job.id)
            else:
                token = uuid4()
                job.status = "running"
                job.attempts += 1
                job.lease_owner = worker_id
                job.lease_token = token
                job.lease_expires_at = now + timedelta(seconds=lease_seconds)
                job.heartbeat_at = now
                job.error_code = None
                job.error_message = None
                await session.flush()
                leased = LeasedJob(
                    id=job.id,
                    asset_id=job.asset_id,
                    generation_id=job.generation_id,
                    stage=job.stage,
                    payload=dict(job.payload),
                    attempts=job.attempts,
                    max_attempts=job.max_attempts,
                    worker_id=worker_id,
                    lease_token=token,
                )

    if expired is not None:
        asset_id, generation_id, job_id = expired
        async with session_factory() as session:
            async with session.begin():
                asset = None
                if asset_id is not None:
                    asset = await session.scalar(
                        select(Asset).where(Asset.id == asset_id).with_for_update()
                    )
                current_job = await session.scalar(
                    select(IngestionJob)
                    .where(IngestionJob.id == job_id)
                    .with_for_update()
                )
                if (
                    current_job is not None
                    and current_job.status == "failed"
                    and current_job.error_code == "lease_expired"
                    and generation_id is not None
                ):
                    generation = await session.scalar(
                        select(ProcessingGeneration)
                        .where(ProcessingGeneration.id == generation_id)
                        .with_for_update()
                    )
                    if generation is not None and generation.state != "active":
                        generation.state = "failed"
                        latest_generation_id = await session.scalar(
                            select(ProcessingGeneration.id)
                            .where(ProcessingGeneration.asset_id == asset_id)
                            .order_by(ProcessingGeneration.created_at.desc())
                            .limit(1)
                        )
                        if (
                            asset is not None
                            and asset.active_generation_id is None
                            and latest_generation_id == generation.id
                        ):
                            asset.state = "failed"
        return None
    return leased


async def renew_lease(
    session_factory: async_sessionmaker,
    job: LeasedJob,
    lease_seconds: int,
    progress: float | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    values: dict[str, Any] = {
        "heartbeat_at": now,
        "lease_expires_at": now + timedelta(seconds=lease_seconds),
    }
    if progress is not None:
        values["progress"] = max(0.0, min(1.0, progress))
    async with session_factory() as session:
        result = await session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job.id,
                IngestionJob.status == "running",
                IngestionJob.lease_token == job.lease_token,
                IngestionJob.lease_expires_at > now,
                IngestionJob.cancellation_requested.is_(False),
            )
            .values(**values)
        )
        await session.commit()
    if result.rowcount != 1:
        raise LeaseLost(f"worker lost the lease for job {job.id}")


async def cancellation_requested(
    session_factory: async_sessionmaker, job: LeasedJob
) -> bool:
    async with session_factory() as session:
        current = await session.get(IngestionJob, job.id)
        return (
            current is None
            or current.lease_token != job.lease_token
            or current.cancellation_requested
        )


async def complete_job(session_factory: async_sessionmaker, job: LeasedJob) -> None:
    async with session_factory() as session:
        result = await session.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == job.id,
                IngestionJob.status == "running",
                IngestionJob.lease_token == job.lease_token,
                IngestionJob.lease_expires_at > datetime.now(timezone.utc),
                IngestionJob.cancellation_requested.is_(False),
            )
            .values(
                status="succeeded",
                progress=1.0,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                heartbeat_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    if result.rowcount != 1:
        raise LeaseLost(f"worker cannot complete job {job.id}")


async def fail_job(
    session_factory: async_sessionmaker,
    job: LeasedJob,
    error: Exception,
    retry_delay_seconds: float,
) -> None:
    retry = job.attempts < job.max_attempts
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        async with session.begin():
            asset = None
            if job.asset_id is not None:
                asset = await session.scalar(
                    select(Asset).where(Asset.id == job.asset_id).with_for_update()
                )
            current_job = await session.scalar(
                select(IngestionJob)
                .where(
                    IngestionJob.id == job.id,
                    IngestionJob.status == "running",
                    IngestionJob.lease_token == job.lease_token,
                    IngestionJob.lease_expires_at > now,
                    IngestionJob.cancellation_requested.is_(False),
                )
                .with_for_update()
            )
            if current_job is None:
                raise LeaseLost(f"worker cannot fail job {job.id}")
            current_job.status = "retry" if retry else "failed"
            current_job.available_at = now + timedelta(seconds=retry_delay_seconds)
            current_job.error_code = type(error).__name__[:128]
            current_job.error_message = str(error)[:4000]
            current_job.lease_owner = None
            current_job.lease_token = None
            current_job.lease_expires_at = None
            if not retry and job.generation_id is not None:
                generation = await session.scalar(
                    select(ProcessingGeneration)
                    .where(ProcessingGeneration.id == job.generation_id)
                    .with_for_update()
                )
                if generation is not None and generation.state != "active":
                    generation.state = "failed"
                    latest_generation_id = await session.scalar(
                        select(ProcessingGeneration.id)
                        .where(ProcessingGeneration.asset_id == job.asset_id)
                        .order_by(ProcessingGeneration.created_at.desc())
                        .limit(1)
                    )
                    if (
                        asset is not None
                        and asset.active_generation_id is None
                        and latest_generation_id == generation.id
                    ):
                        asset.state = "failed"


async def activate_generation(
    session,
    asset_id: UUID,
    generation_id: UUID,
    job: LeasedJob,
) -> None:
    """Publish a complete generation only while its worker lease remains valid."""
    now = datetime.now(timezone.utc)
    asset = await session.scalar(
        select(Asset).where(Asset.id == asset_id).with_for_update()
    )
    current_job = await session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.id == job.id,
            IngestionJob.status == "running",
            IngestionJob.lease_token == job.lease_token,
            IngestionJob.lease_expires_at > now,
            IngestionJob.cancellation_requested.is_(False),
        )
        .with_for_update()
    )
    if current_job is None:
        raise LeaseLost(f"worker cannot activate generation for stale job {job.id}")
    if current_job.asset_id != asset_id or current_job.generation_id != generation_id:
        raise LeaseLost(f"job {job.id} does not own the requested generation")
    generation = await session.scalar(
        select(ProcessingGeneration)
        .where(ProcessingGeneration.id == generation_id)
        .with_for_update()
    )
    if asset is None or generation is None or generation.asset_id != asset_id:
        raise ValueError("generation does not belong to the requested asset")
    if generation.state != "complete":
        raise ValueError("only a complete generation can become active")
    if asset.state in {"deleting", "deleted"}:
        raise ValueError("cannot activate a generation for a deleted asset")
    previous_id = asset.active_generation_id
    if previous_id and previous_id != generation.id:
        previous = await session.get(ProcessingGeneration, previous_id)
        if previous is not None:
            previous.state = "superseded"
            previous.activated_at = None
    asset.active_generation_id = generation.id
    asset.state = "ready"
    generation.state = "active"
    generation.activated_at = now
