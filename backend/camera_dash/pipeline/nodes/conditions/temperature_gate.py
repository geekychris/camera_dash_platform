"""Thermal-specific condition: route through `match` when any sampled pixel exceeds threshold.

Pairs naturally with a ``source.camera`` of a FLIR Lepton + an optional upstream
``detector`` that gives bounding boxes (so we can sample only inside them).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ....pipeline.types import DetectionSet, Event, Frame, PortType
from ...node import Node, Port


class TemperatureGateNode(Node):
    TYPE_ID = "condition.temperature_gate"
    UI_CATEGORY = "condition"
    INPUTS = (
        Port("frame", PortType.FRAME),
        Port("detections", PortType.DETECTIONS, required=False),
    )
    OUTPUTS = (
        Port("match", PortType.EVENT, required=False),
        Port("no_match", PortType.EVENT, required=False),
    )
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "min_celsius": {"type": "number", "default": 38.0},
            "max_celsius": {"type": "number", "default": 200.0},
            "region": {"type": "string", "enum": ["whole", "bbox"], "default": "whole",
                       "description": "`bbox` requires `detections` input"},
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None or frame.radiometric is None:
            return {}
        lo = float(self.config.get("min_celsius", 38.0))
        hi = float(self.config.get("max_celsius", 200.0))
        region = self.config.get("region", "whole")
        radio = frame.radiometric  # uint16 centi-Kelvin
        celsius = radio.astype(np.float32) / 100.0 - 273.15

        dets: DetectionSet | None = inputs.get("detections")
        regions: list[tuple[int, int, int, int]]
        if region == "bbox" and dets is not None and dets.detections:
            regions = [(max(0, int(d.bbox[0])), max(0, int(d.bbox[1])),
                        min(frame.width, int(d.bbox[0] + d.bbox[2])),
                        min(frame.height, int(d.bbox[1] + d.bbox[3])))
                       for d in dets.detections]
        else:
            regions = [(0, 0, frame.width, frame.height)]

        hottest: float | None = None
        hot_at: tuple[int, int] | None = None
        for x1, y1, x2, y2 in regions:
            if x2 <= x1 or y2 <= y1:
                continue
            sub = celsius[y1:y2, x1:x2]
            yi, xi = np.unravel_index(np.argmax(sub), sub.shape)
            t = float(sub[yi, xi])
            if hottest is None or t > hottest:
                hottest = t
                hot_at = (int(x1 + xi), int(y1 + yi))

        if hottest is None:
            return {}

        in_range = lo <= hottest <= hi
        evt = Event(
            pipeline_id=self.context.pipeline_id, node_id=self.node_id,
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            kind="temperature_gate",
            payload={"hottest_celsius": hottest, "hot_at": hot_at,
                     "threshold_low": lo, "threshold_high": hi,
                     "matched": in_range},
        )
        if self.context.event_bus is not None:
            self.context.event_bus.publish_nowait(evt)
        return {"match": evt} if in_range else {"no_match": evt}
