"""Registry of derived streams — pipeline-produced video streams that are not
backed by a physical camera. Populated by ``sink.stream`` nodes at setup time.

The dashboard fetches these via ``/api/streams`` and renders them as tiles
alongside the physical cameras.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DerivedStream:
    id: str                       # e.g. "derived/<pipeline>/<node>"
    pipeline_id: str
    node_id: str
    label: str
    source_camera_id: str | None  # the camera this stream derives from, if known
    width: int
    height: int
    fps: int
    metadata: dict[str, Any] = field(default_factory=dict)


class DerivedStreamRegistry:
    def __init__(self) -> None:
        self._items: dict[str, DerivedStream] = {}
        self._lock = asyncio.Lock()

    async def add(self, stream: DerivedStream) -> None:
        async with self._lock:
            self._items[stream.id] = stream

    async def remove(self, stream_id: str) -> None:
        async with self._lock:
            self._items.pop(stream_id, None)

    def list(self) -> list[DerivedStream]:
        return list(self._items.values())

    def get(self, stream_id: str) -> DerivedStream | None:
        return self._items.get(stream_id)
