"""Crop a fixed ROI from a frame."""

from __future__ import annotations

from typing import Any

from ....pipeline.types import Frame, PortType
from ...node import Node, Port


class CropNode(Node):
    TYPE_ID = "transform.crop"
    UI_CATEGORY = "transform"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["x", "y", "width", "height"],
        "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"},
            "width": {"type": "integer"}, "height": {"type": "integer"},
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        x = max(0, int(self.config["x"]))
        y = max(0, int(self.config["y"]))
        w = min(int(self.config["width"]), frame.width - x)
        h = min(int(self.config["height"]), frame.height - y)
        data = frame.data[y:y + h, x:x + w]
        radio = frame.radiometric[y:y + h, x:x + w] if frame.radiometric is not None else None
        return {"frame": Frame(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            width=w, height=h, pixel_format=frame.pixel_format, data=data,
            radiometric=radio, metadata=frame.metadata,
        )}
