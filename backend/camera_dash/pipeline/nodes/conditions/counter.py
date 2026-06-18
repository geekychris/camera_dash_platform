"""Count-threshold condition — fire when N or more detections match a label."""

from __future__ import annotations

from typing import Any

from ....pipeline.types import DetectionSet, Event, PortType
from ...node import Node, Port


class CounterNode(Node):
    TYPE_ID = "condition.counter"
    UI_CATEGORY = "condition"
    INPUTS = (Port("payload", PortType.DETECTIONS),)
    OUTPUTS = (
        Port("match", PortType.EVENT, required=False),
        Port("no_match", PortType.DETECTIONS, required=False),
    )
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "default": "",
                       "description": "Class to count (empty = all)"},
            "min_count": {"type": "integer", "default": 2, "minimum": 1},
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        dets: DetectionSet | None = inputs.get("payload")
        if dets is None:
            return {}
        wanted = self.config.get("label", "") or ""
        threshold = int(self.config.get("min_count", 2))
        count = sum(1 for d in dets.detections if not wanted or d.label == wanted)
        if count < threshold:
            return {"no_match": dets}
        evt = Event(
            pipeline_id=self.context.pipeline_id, node_id=self.node_id,
            camera_id=dets.camera_id, timestamp_ns=dets.timestamp_ns,
            kind="counter",
            payload={"label": wanted or "*", "count": count, "min_count": threshold},
        )
        if self.context.event_bus is not None:
            self.context.event_bus.publish_nowait(evt)
        return {"match": evt}
