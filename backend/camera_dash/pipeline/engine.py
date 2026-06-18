"""Async pipeline executor — one task per node, typed queues per edge."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from ..settings import Settings, substitute
from .graph import Graph
from .node import Inbox, Node, NodeContext, Outbox
from .types import PORT_TYPE_DROP_OLDEST, PORT_TYPE_QUEUE_DEPTH, PortType

log = logging.getLogger(__name__)


class PipelineEngine:
    """Owns the set of running pipelines.

    Pipelines are stored in memory as :class:`Graph` instances; each can be
    started, stopped, or hot-replaced. Boots zero pipelines initially — the API
    loads/starts them on demand (and on startup if persisted in storage).
    """

    def __init__(
        self,
        settings: Settings,
        catalog: dict[str, type[Node]],
        frame_bus: Any,
        camera_manager: Any,
        event_bus: Any = None,
        streaming: Any = None,
        derived_streams: Any = None,
        ring_buffers: Any = None,
    ) -> None:
        self.settings = settings
        self.catalog = catalog
        self.frame_bus = frame_bus
        self.camera_manager = camera_manager
        self.event_bus = event_bus
        self.streaming = streaming
        self.derived_streams = derived_streams
        self.ring_buffers = ring_buffers
        self._runs: dict[str, _RunningPipeline] = {}

    async def start(self) -> None:
        """Engine itself has no work — pipelines start individually."""

    async def stop(self) -> None:
        await asyncio.gather(*(r.stop() for r in self._runs.values()), return_exceptions=True)
        self._runs.clear()

    async def start_pipeline(self, graph: Graph) -> None:
        if graph.id in self._runs:
            await self.stop_pipeline(graph.id)
        run = _RunningPipeline(graph, self.settings, self.catalog,
                               self.frame_bus, self.camera_manager, self.event_bus,
                               self.streaming, self.derived_streams, self.ring_buffers)
        await run.start()
        self._runs[graph.id] = run

    async def stop_pipeline(self, pipeline_id: str) -> None:
        run = self._runs.pop(pipeline_id, None)
        if run:
            await run.stop()

    def status(self) -> dict[str, dict[str, Any]]:
        return {pid: r.status() for pid, r in self._runs.items()}


class _RunningPipeline:
    def __init__(
        self,
        graph: Graph,
        settings: Settings,
        catalog: dict[str, type[Node]],
        frame_bus: Any,
        camera_manager: Any,
        event_bus: Any = None,
        streaming: Any = None,
        derived_streams: Any = None,
        ring_buffers: Any = None,
    ) -> None:
        self.graph = graph
        self.settings = settings
        self.catalog = catalog
        self.frame_bus = frame_bus
        self.camera_manager = camera_manager
        self.event_bus = event_bus
        self.streaming = streaming
        self.derived_streams = derived_streams
        self.ring_buffers = ring_buffers
        self._tasks: list[asyncio.Task[Any]] = []
        self._nodes: dict[str, Node] = {}
        self._inboxes: dict[str, Inbox] = {}
        self._outboxes: dict[str, Outbox] = {}

    async def start(self) -> None:
        ctx = NodeContext(
            pipeline_id=self.graph.id,
            settings=self.settings,
            camera_manager=self.camera_manager,
            frame_bus=self.frame_bus,
            event_bus=self.event_bus,
            streaming=self.streaming,
            derived_streams=self.derived_streams,
            ring_buffers=self.ring_buffers,
        )
        # Instantiate nodes
        for gn in self.graph.nodes:
            node_cls = self.catalog[gn.type]
            resolved_config = substitute(gn.config, self.settings)
            node = node_cls(node_id=gn.id, config=resolved_config, context=ctx)
            self._nodes[gn.id] = node

        # Build edge queues: one queue per edge, sized by port type
        # edge_queues[(src_node, src_port)] -> list of (dst_node, dst_port, queue)
        out_fanout: dict[str, dict[str, list[asyncio.Queue[Any]]]] = defaultdict(lambda: defaultdict(list))
        out_drop: dict[str, dict[str, bool]] = defaultdict(dict)
        in_queues: dict[str, dict[str, asyncio.Queue[Any]]] = defaultdict(dict)
        in_required: dict[str, set[str]] = defaultdict(set)

        # Mark required input ports per node
        for gn in self.graph.nodes:
            node_cls = self.catalog[gn.type]
            for p in node_cls.INPUTS:
                if p.required:
                    in_required[gn.id].add(p.name)

        # Build queues per edge
        for e in self.graph.edges:
            src_cls = self.catalog[next(n.type for n in self.graph.nodes if n.id == e.from_node)]
            src_port: PortType = next(p.port_type for p in src_cls.OUTPUTS if p.name == e.from_port)
            depth = PORT_TYPE_QUEUE_DEPTH[src_port]
            q: asyncio.Queue[Any] = asyncio.Queue(maxsize=depth)
            out_fanout[e.from_node][e.from_port].append(q)
            out_drop[e.from_node][e.from_port] = PORT_TYPE_DROP_OLDEST[src_port]
            in_queues[e.to_node][e.to_port] = q  # one queue per input port

        # Set up inbox/outbox per node
        for gn in self.graph.nodes:
            self._inboxes[gn.id] = Inbox(in_queues.get(gn.id, {}), in_required.get(gn.id, set()))
            self._outboxes[gn.id] = Outbox(out_fanout.get(gn.id, {}), out_drop.get(gn.id, {}))

        # setup + spawn
        await asyncio.gather(*(n.setup() for n in self._nodes.values()))
        for gn in self.graph.nodes:
            node = self._nodes[gn.id]
            self._tasks.append(asyncio.create_task(
                self._run_node(node), name=f"pipeline/{self.graph.id}/{gn.id}"
            ))
        log.info("pipeline %s started with %d nodes", self.graph.id, len(self._nodes))

    async def _run_node(self, node: Node) -> None:
        try:
            await node.run(self._inboxes[node.node_id], self._outboxes[node.node_id])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("node %s/%s crashed", self.graph.id, node.node_id)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await asyncio.gather(*(n.teardown() for n in self._nodes.values()), return_exceptions=True)
        log.info("pipeline %s stopped", self.graph.id)

    def status(self) -> dict[str, Any]:
        return {
            "id": self.graph.id,
            "nodes": [{"id": gn.id, "type": gn.type} for gn in self.graph.nodes],
            "running": sum(1 for t in self._tasks if not t.done()),
        }
