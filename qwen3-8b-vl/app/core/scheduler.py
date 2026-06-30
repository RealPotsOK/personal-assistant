from __future__ import annotations

import asyncio
import heapq
import itertools
from contextlib import asynccontextmanager

PRIORITIES = {"realtime": 0, "normal": 10, "background": 20}


class PriorityGate:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active = False
        self._counter = itertools.count()
        self._waiting: list[tuple[int, int, asyncio.Future]] = []

    @asynccontextmanager
    async def slot(self, priority: str = "normal"):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        item = (PRIORITIES.get(priority, PRIORITIES["normal"]), next(self._counter), future)
        async with self._condition:
            heapq.heappush(self._waiting, item)
            self._grant_next()
        try:
            await future
        except BaseException:
            async with self._condition:
                if future.done() and not future.cancelled():
                    self._active = False
                elif not future.done():
                    future.cancel()
                self._waiting = [entry for entry in self._waiting if entry[2] is not future]
                heapq.heapify(self._waiting)
                self._grant_next()
            raise
        try:
            yield
        finally:
            async with self._condition:
                self._active = False
                self._grant_next()

    def _grant_next(self) -> None:
        if self._active:
            return
        while self._waiting:
            _, _, future = heapq.heappop(self._waiting)
            if future.cancelled():
                continue
            self._active = True
            future.set_result(None)
            return

    @property
    def queue_depth(self) -> int:
        return len(self._waiting)
