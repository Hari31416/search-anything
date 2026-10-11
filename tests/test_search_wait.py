"""Bounded waits release sessions and listeners, including on cancellation."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from search_anything.events import wait_for_search
from search_anything.settings import Settings


def test_wait_configuration():
    assert Settings(_env_file=None).query_wait_seconds == 5
    assert Settings(_env_file=None, query_wait_seconds=0).query_wait_seconds == 0
    for value in (-1, 5.1):
        with pytest.raises(ValueError):
            Settings(_env_file=None, query_wait_seconds=value)


@pytest.mark.asyncio
async def test_disabled_wait_does_not_connect():
    factory = MagicMock()
    assert await wait_for_search(factory, "unused", uuid4(), uuid4(), 0) is None
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_wait_releases_resources(monkeypatch, cancel):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.scalar.return_value = None
    factory = MagicMock(return_value=session)
    entered_wait = asyncio.Event()
    listener = AsyncMock()
    listener.__aenter__.return_value = listener
    listener.connected = True
    listener.event = MagicMock()

    async def block(_):
        entered_wait.set()
        await asyncio.Future()

    listener.wait.side_effect = block
    monkeypatch.setattr(
        "search_anything.events.WorkWakeup", MagicMock(return_value=listener)
    )
    task = asyncio.create_task(
        wait_for_search(factory, "unused", uuid4(), uuid4(), 0.05)
    )
    await entered_wait.wait()
    # The database transaction has ended before waiting for a notification.
    session.__aexit__.assert_awaited_once()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert await task is None
    listener.__aexit__.assert_awaited_once()
