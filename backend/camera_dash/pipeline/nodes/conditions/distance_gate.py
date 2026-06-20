"""Depth-aware gate: route through ``match`` when enough of the scene falls inside a distance band.

Pairs with ``source.camera_depth`` (Kinect, OAK-D, etc.). Useful for crude
proximity triggers — "anything within 1.5 m of the camera" — without needing
a full object detector.

The check excludes invalid pixels (zeros from libfreenect mean "no reading",
not "zero distance"). If fewer than ``min_valid_pct`` of pixels are valid in
the chosen region the gate emits nothing — the depth stream is too sparse to
trust the answer.
"""

from __future__ import annotations

from typing import Any

from ....pipeline.types import DepthFrame, Event, PortType
from ...node import Node, Port


class DistanceGateNode(Node):
    TYPE_ID = "condition.distance_gate"
    UI_CATEGORY = "condition"
    INPUTS = (Port("depth", PortType.DEPTH_FRAME),)
    OUTPUTS = (
        Port("match", PortType.EVENT, required=False),
        Port("no_match", PortType.EVENT, required=False),
    )
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "min_mm": {"type": "integer", "default": 500, "minimum": 0,
                       "description": "Lower bound of the distance band, in millimetres"},
            "max_mm": {"type": "integer", "default": 1500, "minimum": 1,
                       "description": "Upper bound of the distance band, in millimetres"},
            "min_coverage_pct": {"type": "number", "default": 2.0, "minimum": 0.0, "maximum": 100.0,
                                  "description": "Minimum % of valid pixels in-band to trigger `match`"},
            "min_valid_pct": {"type": "number", "default": 10.0, "minimum": 0.0, "maximum": 100.0,
                              "description": "Need at least this % of pixels with a valid reading to evaluate"},
            "roi": {
                "type": "object",
                "description": "Optional rectangular region in normalized [0,1] coords",
                "properties": {
                    "x": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.0},
                    "y": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.0},
                    "w": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 1.0},
                    "h": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 1.0},
                },
            },
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        depth_frame: DepthFrame | None = inputs.get("depth")
        if depth_frame is None:
            return {}
        lo = int(self.config.get("min_mm", 500))
        hi = int(self.config.get("max_mm", 1500))
        if hi <= lo:
            return {}
        min_coverage_pct = float(self.config.get("min_coverage_pct", 2.0))
        min_valid_pct = float(self.config.get("min_valid_pct", 10.0))

        data = depth_frame.data
        roi = self.config.get("roi") or {}
        x = max(0, min(depth_frame.width - 1, int(float(roi.get("x", 0.0)) * depth_frame.width)))
        y = max(0, min(depth_frame.height - 1, int(float(roi.get("y", 0.0)) * depth_frame.height)))
        w = max(1, int(float(roi.get("w", 1.0)) * depth_frame.width))
        h = max(1, int(float(roi.get("h", 1.0)) * depth_frame.height))
        sub = data[y:y + h, x:x + w]

        total = sub.size
        valid_mask = sub > 0
        valid = int(valid_mask.sum())
        if total == 0 or 100.0 * valid / total < min_valid_pct:
            return {}
        in_band = int(((sub >= lo) & (sub <= hi)).sum())
        coverage_pct = 100.0 * in_band / valid if valid else 0.0
        matched = coverage_pct >= min_coverage_pct

        evt = Event(
            pipeline_id=self.context.pipeline_id,
            node_id=self.node_id,
            camera_id=depth_frame.camera_id,
            timestamp_ns=depth_frame.timestamp_ns,
            kind="distance_gate",
            payload={
                "min_mm": lo,
                "max_mm": hi,
                "coverage_pct": round(coverage_pct, 2),
                "valid_pct": round(100.0 * valid / total, 2),
                "nearest_mm": int(sub[valid_mask].min()) if valid else None,
                "matched": matched,
                "roi": {"x": x, "y": y, "w": w, "h": h},
            },
        )
        if self.context.event_bus is not None:
            self.context.event_bus.publish_nowait(evt)
        return {"match": evt} if matched else {"no_match": evt}
