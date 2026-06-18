"""Process-local pub-sub for pipeline Events (used by SSE)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from ..pipeline.types import Event


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._lock = asyncio.Lock()

    async def subscribe(self, depth: int = 256) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=depth)
        async with self._lock:
            self._subscribers.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        async with self._lock:
            with contextlib.suppress(ValueError):
                self._subscribers.remove(q)

    def publish_nowait(self, event: Event) -> None:
        for q in list(self._subscribers):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(event)

    async def stream(self) -> AsyncIterator[Event]:
        q = await self.subscribe()
        try:
            while True:
                yield await q.get()
        finally:
            await self.unsubscribe(q)
