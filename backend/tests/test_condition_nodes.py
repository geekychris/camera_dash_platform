from __future__ import annotations

import numpy as np
import pytest

from camera_dash.pipeline.node import NodeContext
from camera_dash.pipeline.nodes.conditions.metadata_match import MetadataMatchNode
from camera_dash.pipeline.nodes.conditions.temperature_gate import TemperatureGateNode
from camera_dash.pipeline.types import Detection, DetectionSet, Frame, PixelFormat


def _ctx():
    return NodeContext(pipeline_id="t", settings=None, camera_manager=None,
                       frame_bus=None, event_bus=None)


@pytest.mark.asyncio
async def test_metadata_match_routes_through_match():
    n = MetadataMatchNode(node_id="m", config={"expression": "d.label == 'person'"}, context=_ctx())
    await n.setup()
    ds = DetectionSet(camera_id="c", timestamp_ns=0, detections=[
        Detection(label="person", score=0.9, bbox=(0, 0, 1, 1)),
    ])
    out = await n.process(detections=ds)
    assert "match" in out and "no_match" not in out


@pytest.mark.asyncio
async def test_metadata_match_routes_through_no_match():
    n = MetadataMatchNode(node_id="m", config={"expression": "d.label == 'dog'"}, context=_ctx())
    await n.setup()
    ds = DetectionSet(camera_id="c", timestamp_ns=0, detections=[
        Detection(label="person", score=0.9, bbox=(0, 0, 1, 1)),
    ])
    out = await n.process(detections=ds)
    assert "no_match" in out and "match" not in out


@pytest.mark.asyncio
async def test_metadata_match_rejects_disallowed_expression():
    n = MetadataMatchNode(node_id="m", config={"expression": "__import__('os')"}, context=_ctx())
    with pytest.raises(ValueError):
        await n.setup()


@pytest.mark.asyncio
async def test_temperature_gate_fires_when_pixel_exceeds_threshold():
    n = TemperatureGateNode(node_id="t", config={"min_celsius": 30.0, "region": "whole"},
                            context=_ctx())
    # 50C ≈ 32315 cK; build a small radiometric matrix where the max is 50C, ambient is 20C
    radio = np.full((4, 4), int((20 + 273.15) * 100), dtype=np.uint16)
    radio[2, 2] = int((50 + 273.15) * 100)
    frame = Frame(camera_id="flir", timestamp_ns=0, width=4, height=4,
                  pixel_format=PixelFormat.THERMAL14,
                  data=np.zeros((4, 4, 3), dtype=np.uint8), radiometric=radio)
    out = await n.process(frame=frame)
    assert "match" in out
    evt = out["match"]
    assert evt.kind == "temperature_gate"
    assert evt.payload["hottest_celsius"] == pytest.approx(50.0, abs=0.01)
    assert evt.payload["hot_at"] == (2, 2)


@pytest.mark.asyncio
async def test_temperature_gate_no_match_when_below_threshold():
    n = TemperatureGateNode(node_id="t", config={"min_celsius": 60.0, "region": "whole"},
                            context=_ctx())
    radio = np.full((4, 4), int((20 + 273.15) * 100), dtype=np.uint16)
    frame = Frame(camera_id="flir", timestamp_ns=0, width=4, height=4,
                  pixel_format=PixelFormat.THERMAL14,
                  data=np.zeros((4, 4, 3), dtype=np.uint8), radiometric=radio)
    out = await n.process(frame=frame)
    assert "no_match" in out
