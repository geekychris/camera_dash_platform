"""Registry of broadcast snapshots — latest JPEG per ``broadcast.snapshot`` node.

Each entry maps a stream id to the most recent JPEG bytes plus the timestamp
of when it was produced. The HTTP API reads from here to serve
``/api/broadcast/snapshot/<id>.jpg`` to any embedder (an `<img>` tag, OBS,
Grafana, a low-tech dashboard).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SnapshotEntry:
    id: str
    pipeline_id: str
    node_id: str
    label: str
    width: int
    height: int
    jpeg: bytes
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class SnapshotRegistry:
    def __init__(self) -> None:
        self._items: dict[str, SnapshotEntry] = {}
        self._lock = asyncio.Lock()

    async def update(self, entry: SnapshotEntry) -> None:
        async with self._lock:
            self._items[entry.id] = entry

    async def remove(self, stream_id: str) -> None:
        async with self._lock:
            self._items.pop(stream_id, None)

    def get(self, stream_id: str) -> SnapshotEntry | None:
        return self._items.get(stream_id)

    def list(self) -> list[SnapshotEntry]:
        return list(self._items.values())
