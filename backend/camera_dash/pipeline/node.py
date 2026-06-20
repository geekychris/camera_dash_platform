"""Pipeline node base class with typed input / output ports."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, ClassVar

from .types import PortType


@dataclass(frozen=True, slots=True)
class Port:
    name: str
    port_type: PortType
    required: bool = True


class Node:
    """Base class for all pipeline nodes.

    Subclasses declare ``INPUTS`` / ``OUTPUTS`` as tuples of :class:`Port`,
    a JSON schema for their configuration, and implement either:

    * ``async def process(self, **inputs) -> dict[str, Any]`` — stateless: read one
      item from each input, return a dict mapping output name -> value. The engine
      will await this in a loop.
    * ``async def run(self, inbox, outbox) -> None`` — full control over the loop.
      Use for sources, sinks, anything that doesn't follow a one-in-one-out shape.
    """

    TYPE_ID: ClassVar[str] = ""
    INPUTS: ClassVar[tuple[Port, ...]] = ()
    OUTPUTS: ClassVar[tuple[Port, ...]] = ()
    CONFIG_SCHEMA: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    UI_CATEGORY: ClassVar[str] = "misc"  # for editor palette grouping

    def __init__(self, node_id: str, config: dict[str, Any], context: NodeContext) -> None:
        self.node_id = node_id
        self.config = config
        self.context = context

    async def setup(self) -> None:
        """Hook for lazy resource init (load model, open socket)."""

    async def teardown(self) -> None:
        """Hook for resource release."""

    async def process(self, **inputs: Any) -> dict[str, Any]:
        """Default no-op. Override for stateless nodes."""
        return {}

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        """Default loop: read one item per input, call process, fan out outputs.

        Override for sources / sinks / anything that doesn't fit a per-tick shape.
        """
        if not self.INPUTS:
            return  # source nodes must override
        while True:
            try:
                inputs = await inbox.read_all()
            except asyncio.CancelledError:
                raise
            if inputs is None:
                return  # upstream closed
            outputs = await self.process(**inputs)
            await outbox.publish(outputs)


@dataclass
class NodeContext:
    """Engine-provided helpers for nodes."""

    pipeline_id: str
    settings: Any  # avoid circular import; this is a Settings instance
    camera_manager: Any
    frame_bus: Any
    event_bus: Any = None        # streaming.event_bus.EventBus
    streaming: Any = None        # streaming.gst.StreamingManager
    derived_streams: Any = None  # streaming.registry.DerivedStreamRegistry
    ring_buffers: Any = None     # recording.ring_buffer.RingBufferManager
    snapshots: Any = None        # streaming.snapshot_registry.SnapshotRegistry


class Inbox:
    """Aggregates one queue per input port; reads a tick of inputs."""

    def __init__(self, queues: dict[str, asyncio.Queue[Any]], required: set[str]) -> None:
        self._queues = queues
        self._required = required
        self._closed = False

    async def read_all(self) -> dict[str, Any] | None:
        if not self._queues:
            return {}
        # Read one item from each required port. Optional ports get latest non-blocking.
        result: dict[str, Any] = {}
        for name, q in self._queues.items():
            if name in self._required:
                item = await q.get()
                if item is _SENTINEL_CLOSE:
                    self._closed = True
                    return None
                result[name] = item
            else:
                try:
                    item = q.get_nowait()
                    if item is _SENTINEL_CLOSE:
                        self._closed = True
                        return None
                    result[name] = item
                except asyncio.QueueEmpty:
                    result[name] = None
        return result


class Outbox:
    """Routes a dict of {port_name: value} to all downstream queues."""

    def __init__(self, fanout: dict[str, list[asyncio.Queue[Any]]],
                 drop_oldest: dict[str, bool]) -> None:
        self._fanout = fanout
        self._drop_oldest = drop_oldest

    async def publish(self, outputs: dict[str, Any]) -> None:
        for name, value in outputs.items():
            if value is None:
                continue
            queues = self._fanout.get(name, [])
            drop = self._drop_oldest.get(name, False)
            for q in queues:
                if drop:
                    # Latest-wins: drop oldest if full
                    if q.full():
                        with contextlib.suppress(asyncio.QueueEmpty):
                            q.get_nowait()
                    q.put_nowait(value)
                else:
                    await q.put(value)

    async def close(self) -> None:
        for queues in self._fanout.values():
            for q in queues:
                await q.put(_SENTINEL_CLOSE)


_SENTINEL_CLOSE: Any = object()
