"""End-to-end pipeline engine test with synthetic source + capture sink.

Verifies that frames flow through a custom Source -> Transform -> Sink graph,
that latest-wins backpressure doesn't deadlock, and that stop() shuts cleanly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pytest

from camera_dash.pipeline.engine import PipelineEngine
from camera_dash.pipeline.graph import Graph
from camera_dash.pipeline.node import Inbox, Node, Outbox, Port
from camera_dash.pipeline.types import Frame, PixelFormat, PortType


class _SyntheticSource(Node):
    TYPE_ID = "test.synth_source"
    INPUTS = ()
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {"type": "object", "properties": {
        "count": {"type": "integer"}, "delay_s": {"type": "number"},
    }}

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        count = int(self.config.get("count", 5))
        delay = float(self.config.get("delay_s", 0.001))
        for i in range(count):
            f = Frame(camera_id="synth", timestamp_ns=i, width=4, height=4,
                      pixel_format=PixelFormat.BGR,
                      data=np.full((4, 4, 3), i, dtype=np.uint8))
            await outbox.publish({"frame": f})
            await asyncio.sleep(delay)


class _PassThrough(Node):
    TYPE_ID = "test.passthrough"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {"type": "object", "properties": {}}

    async def process(self, **inputs: Any) -> dict[str, Any]:
        return {"frame": inputs.get("frame")}


class _CaptureSink(Node):
    TYPE_ID = "test.capture"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {"type": "object", "properties": {}}
    captured: list[Frame] = []

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            frame = inputs.get("frame")
            if frame is not None:
                _CaptureSink.captured.append(frame)


CATALOG = {
    "test.synth_source": _SyntheticSource,
    "test.passthrough": _PassThrough,
    "test.capture": _CaptureSink,
}


class _Settings:
    class profile:
        pass


@pytest.mark.asyncio
async def test_engine_runs_a_graph():
    _CaptureSink.captured.clear()
    settings = _Settings()
    settings.profile = type("P", (), {})()
    engine = PipelineEngine(settings=settings, catalog=CATALOG,
                            frame_bus=object(), camera_manager=object())
    graph = Graph.from_json({
        "id": "t",
        "name": "t",
        "nodes": [
            {"id": "src", "type": "test.synth_source", "config": {"count": 5, "delay_s": 0.001}},
            {"id": "pt", "type": "test.passthrough", "config": {}},
            {"id": "snk", "type": "test.capture", "config": {}},
        ],
        "edges": [
            {"from": "src.frame", "to": "pt.frame"},
            {"from": "pt.frame", "to": "snk.frame"},
        ],
    }, catalog=CATALOG)
    await engine.start()
    await engine.start_pipeline(graph)
    # Source emits 5 frames quickly then exits; give the pipeline time to flush
    for _ in range(40):
        if len(_CaptureSink.captured) >= 5:
            break
        await asyncio.sleep(0.02)
    await engine.stop()
    # latest-wins on FRAME port may drop frames; at minimum we got the last one
    assert len(_CaptureSink.captured) >= 1
    assert _CaptureSink.captured[-1].timestamp_ns == 4


@pytest.mark.asyncio
async def test_engine_stops_cleanly_with_no_pipelines():
    engine = PipelineEngine(settings=_Settings(), catalog=CATALOG,
                            frame_bus=object(), camera_manager=object())
    await engine.start()
    await engine.stop()
