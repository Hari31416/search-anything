import asyncio
import threading
import time

import pytest

from search_anything.scheduler import LocalInferenceScheduler


@pytest.mark.asyncio
async def test_query_work_precedes_waiting_ingestion_work() -> None:
    scheduler = LocalInferenceScheduler()
    started = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def blocking_call() -> None:
        started.set()
        release.wait(timeout=2)

    def record(label: str) -> str:
        order.append(label)
        return label

    active = asyncio.create_task(scheduler.submit(blocking_call, kind="ingestion"))
    assert await asyncio.to_thread(started.wait, 1)
    ingestion = asyncio.create_task(
        scheduler.submit(record, "ingestion", kind="ingestion")
    )
    query = asyncio.create_task(scheduler.submit(record, "query", kind="query"))
    await asyncio.sleep(0)
    release.set()
    await active
    assert await query == "query"
    assert await ingestion == "ingestion"
    assert order == ["query", "ingestion"]
    await scheduler.close()


@pytest.mark.asyncio
async def test_model_call_does_not_block_event_loop() -> None:
    scheduler = LocalInferenceScheduler()
    call = asyncio.create_task(scheduler.submit(time.sleep, 0.15))
    started = time.perf_counter()
    await asyncio.sleep(0.01)
    assert time.perf_counter() - started < 0.1
    await call
    await scheduler.close()


@pytest.mark.asyncio
async def test_close_resolves_queued_calls_and_waits_for_active_call() -> None:
    scheduler = LocalInferenceScheduler()
    started = threading.Event()

    def active_call() -> str:
        started.set()
        time.sleep(0.05)
        return "finished"

    active = asyncio.create_task(scheduler.submit(active_call))
    assert await asyncio.to_thread(started.wait, 1)
    queued = asyncio.create_task(scheduler.submit(lambda: "never"))
    await asyncio.sleep(0)
    await scheduler.close()
    assert await active == "finished"
    with pytest.raises(RuntimeError, match="stopped"):
        await queued
