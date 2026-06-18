"""Draw bounding boxes + labels for detections onto the frame."""

from __future__ import annotations

from typing import Any

import cv2

from ....pipeline.types import DetectionSet, Frame, PortType
from ...node import Node, Port


class AnnotateNode(Node):
    TYPE_ID = "transform.annotate"
    UI_CATEGORY = "transform"
    INPUTS = (
        Port("frame", PortType.FRAME),
        Port("detections", PortType.DETECTIONS),
    )
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "color": {"type": "array", "items": {"type": "integer"},
                      "default": [0, 255, 0], "description": "BGR"},
            "thickness": {"type": "integer", "default": 2},
            "show_score": {"type": "boolean", "default": True},
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        dets: DetectionSet | None = inputs.get("detections")
        if frame is None:
            return {}
        color = tuple(int(c) for c in self.config.get("color", [0, 255, 0]))
        thickness = int(self.config.get("thickness", 2))
        show_score = bool(self.config.get("show_score", True))

        img = frame.data.copy()
        if dets is not None:
            for d in dets:
                x, y, w, h = (int(v) for v in d.bbox)
                cv2.rectangle(img, (x, y), (x + w, y + h), color, thickness)
                text = f"{d.label} {d.score:.2f}" if show_score else d.label
                cv2.putText(img, text, (x, max(0, y - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        return {"frame": Frame(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            width=frame.width, height=frame.height,
            pixel_format=frame.pixel_format, data=img,
            radiometric=frame.radiometric, metadata=frame.metadata,
        )}
