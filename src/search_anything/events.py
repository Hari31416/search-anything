"""Postgres dispatch hints; durable jobs remain the source of truth."""

import asyncio
import logging
from contextlib import suppress
from uuid import UUID

from asyncpg import connect as connect_listener
from sqlalchemy import text, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from search_anything.models import IngestionJob

logger = logging.getLogger(__name__)
CHANNEL = "search_anything_work"


async def notify_work(session: AsyncSession) -> None:
    # Postgres delivers this only when the producer's transaction commits.
    await session.execute(text("SELECT pg_notify(:channel, '')"), {"channel": CHANNEL})


class WorkWakeup:
    def __init__(self, database_url: str, channel: str = CHANNEL) -> None:
        self.database_url = database_url
        self.channel = channel
        self.event = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.connected = False

    async def __aenter__(self) -> "WorkWakeup":
        self.task = asyncio.create_task(self._listen())
        return self

    async def __aexit__(self, *args: object) -> None:
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    async def wait(self, timeout: float) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(self.event.wait(), timeout)

    async def _listen(self) -> None:
        url = make_url(self.database_url).set(drivername="postgresql")
        while True:
            conn = None
            try:
                conn = await connect_listener(
                    url.render_as_string(hide_password=False), timeout=5
                )
                await conn.add_listener(self.channel, lambda *_: self.event.set())
                self.connected = True
                # Recheck durable state after subscribing or reconnecting.
                self.event.set()
                while not conn.is_closed():
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Dispatch listener unavailable; polling continues")
            finally:
                self.connected = False
                if conn is not None:
                    with suppress(Exception):
                        conn.terminate()
            await asyncio.sleep(5)


def result_channel(job_id: UUID) -> str:
    return f"search_anything_result_{job_id.hex}"


async def notify_search_result(session: AsyncSession, job_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_notify(:channel, '')"), {"channel": result_channel(job_id)}
    )


async def wait_for_search(
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
    job_id: UUID,
    workspace_id: UUID,
    timeout: float,
) -> IngestionJob | None:
    """Wait on completion hints, rechecking durable state without holding a transaction."""
    if timeout <= 0:
        return None
    async with WorkWakeup(database_url, result_channel(job_id)) as wakeup:
        try:
            async with asyncio.timeout(timeout):
                while True:
                    wakeup.event.clear()
                    async with session_factory() as session:
                        job = await session.scalar(
                            select(IngestionJob).where(
                                IngestionJob.id == job_id,
                                IngestionJob.workspace_id == workspace_id,
                                IngestionJob.stage == "search",
                            )
                        )
                        if job is not None and job.status in {"succeeded", "failed"}:
                            return job
                    # Poll only as a recovery mechanism. Listener establishment
                    # also wakes this loop to close the subscribe/read race.
                    await wakeup.wait(1.0 if wakeup.connected else 0.1)
        except TimeoutError:
            return None
