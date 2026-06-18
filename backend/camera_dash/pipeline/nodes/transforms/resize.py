"""Resize a frame."""

from __future__ import annotations

from typing import Any

import cv2

from ....pipeline.types import Frame, PortType
from ...node import Node, Port


class ResizeNode(Node):
    TYPE_ID = "transform.resize"
    UI_CATEGORY = "transform"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["width", "height"],
        "properties": {
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "interpolation": {"type": "string", "enum": ["linear", "nearest", "area", "cubic"],
                              "default": "area"},
        },
    }

    _INTERP = {"linear": cv2.INTER_LINEAR, "nearest": cv2.INTER_NEAREST,
               "area": cv2.INTER_AREA, "cubic": cv2.INTER_CUBIC}

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        w = int(self.config["width"])
        h = int(self.config["height"])
        interp = self._INTERP[self.config.get("interpolation", "area")]
        data = cv2.resize(frame.data, (w, h), interpolation=interp)
        new = Frame(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            width=w, height=h, pixel_format=frame.pixel_format, data=data,
            radiometric=None,  # discard radiometric coregistration; resize node not for thermal
            metadata=frame.metadata,
        )
        return {"frame": new}
