"""Single-owner, priority scheduler for local model calls."""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(order=True)
class _Request:
    priority: int
    sequence: int
    function: Callable[..., Any] = field(compare=False)
    args: tuple[Any, ...] = field(compare=False)
    kwargs: dict[str, Any] = field(compare=False)
    future: asyncio.Future[Any] | None = field(compare=False)
    stop: bool = field(default=False, compare=False)


class LocalInferenceScheduler:
    """Run one model call at a time, with text/media queries ahead of ingestion."""

    _priorities = {"query": 0, "ingestion": 10}

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[_Request] = asyncio.PriorityQueue()
        self._sequence = itertools.count()
        self._consumer: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        if self._consumer is None:
            self._closed = False
            self._consumer = asyncio.create_task(self._consume())

    async def close(self) -> None:
        self._closed = True
        if self._consumer is not None:
            while not self._queue.empty():
                request = self._queue.get_nowait()
                if request.future is not None and not request.future.done():
                    request.future.set_exception(
                        RuntimeError(
                            "inference scheduler stopped before the call started"
                        )
                    )
                self._queue.task_done()
            stop = _Request(
                -1,
                next(self._sequence),
                lambda: None,
                (),
                {},
                None,
                stop=True,
            )
            await self._queue.put(stop)
            # Wait for an active native/PyTorch call to finish before allowing
            # another scheduler instance to load the same model.
            await self._consumer
            self._consumer = None
        while not self._queue.empty():
            request = self._queue.get_nowait()
            if not request.future.done():
                request.future.cancel()
            self._queue.task_done()

    async def submit(
        self,
        function: Callable[..., Any],
        *args: Any,
        kind: str = "query",
        **kwargs: Any,
    ) -> Any:
        if self._closed:
            raise RuntimeError("inference scheduler is closed")
        if kind not in self._priorities:
            raise ValueError(f"unsupported inference task kind: {kind}")
        await self.start()
        future = asyncio.get_running_loop().create_future()
        request = _Request(
            self._priorities[kind],
            next(self._sequence),
            function,
            args,
            kwargs,
            future,
        )
        await self._queue.put(request)
        return await future

    async def _consume(self) -> None:
        while True:
            request = await self._queue.get()
            try:
                if request.stop:
                    return
                if request.future is None or request.future.cancelled():
                    continue
                try:
                    result = await asyncio.to_thread(
                        request.function, *request.args, **request.kwargs
                    )
                except Exception as error:
                    if not request.future.done():
                        request.future.set_exception(error)
                    logger.exception("Local inference call failed")
                else:
                    if not request.future.done():
                        request.future.set_result(result)
            finally:
                self._queue.task_done()
