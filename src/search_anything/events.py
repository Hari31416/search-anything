"""Postgres dispatch hints; durable jobs remain the source of truth."""

import asyncio
import logging
from contextlib import suppress

from asyncpg import connect as connect_listener
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
CHANNEL = "search_anything_work"


async def notify_work(session: AsyncSession) -> None:
    # Postgres delivers this only when the producer's transaction commits.
    await session.execute(text("SELECT pg_notify(:channel, '')"), {"channel": CHANNEL})


class WorkWakeup:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
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
                await conn.add_listener(CHANNEL, lambda *_: self.event.set())
                self.connected = True
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
                        await conn.close(timeout=5)
            await asyncio.sleep(5)
