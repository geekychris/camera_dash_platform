"""Per-camera asyncio fan-out for live frames.

Cameras publish each captured frame to a single FrameBus; subscribers (pipeline
``source.camera`` nodes, the radiometric WS) get their own queue with latest-wins
semantics, so a slow consumer never stalls capture.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator

from ..pipeline.types import Frame


class FrameBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Frame]]] = defaultdict(list)
        self._lock = asyncio.Lock()
        # Rolling window of publish timestamps per camera for fps calc.
        self._timestamps: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=60))

    async def subscribe(self, camera_id: str, depth: int = 2) -> asyncio.Queue[Frame]:
        q: asyncio.Queue[Frame] = asyncio.Queue(maxsize=depth)
        async with self._lock:
            self._subscribers[camera_id].append(q)
        return q

    async def unsubscribe(self, camera_id: str, q: asyncio.Queue[Frame]) -> None:
        async with self._lock:
            with contextlib.suppress(ValueError):
                self._subscribers[camera_id].remove(q)

    def publish_nowait(self, camera_id: str, frame: Frame) -> None:
        """Drop-oldest fan-out. Safe to call from any task."""
        self._timestamps[camera_id].append(time.monotonic())
        for q in self._subscribers.get(camera_id, ()):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(frame)

    def fps(self, camera_id: str) -> float:
        """Rolling fps over the last ~60 frames (or fewer)."""
        ts = self._timestamps.get(camera_id)
        if not ts or len(ts) < 2:
            return 0.0
        span = ts[-1] - ts[0]
        return (len(ts) - 1) / span if span > 0 else 0.0

    def subscriber_counts(self) -> dict[str, int]:
        return {cam: len(qs) for cam, qs in self._subscribers.items()}

    async def stream(self, camera_id: str, depth: int = 2) -> AsyncIterator[Frame]:
        q = await self.subscribe(camera_id, depth=depth)
        try:
            while True:
                yield await q.get()
        finally:
            await self.unsubscribe(camera_id, q)

    def has_subscribers(self, camera_id: str) -> bool:
        return bool(self._subscribers.get(camera_id))
