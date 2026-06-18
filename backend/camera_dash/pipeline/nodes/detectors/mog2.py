"""MOG2 background subtractor — emits detections for moving blobs."""

from __future__ import annotations

import asyncio
from typing import Any

import cv2

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port


class Mog2Node(Node):
    TYPE_ID = "detector.mog2"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "history": {"type": "integer", "default": 500},
            "var_threshold": {"type": "number", "default": 16},
            "detect_shadows": {"type": "boolean", "default": False},
            "min_area": {"type": "integer", "default": 500},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._bg: Any = None

    async def setup(self) -> None:
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=int(self.config.get("history", 500)),
            varThreshold=float(self.config.get("var_threshold", 16)),
            detectShadows=bool(self.config.get("detect_shadows", False)),
        )

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        min_area = int(self.config.get("min_area", 500))

        def _run() -> list[Detection]:
            mask = self._bg.apply(frame.data)
            _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            out: list[Detection] = []
            for _i, c in enumerate(contours):
                area = cv2.contourArea(c)
                if area < min_area:
                    continue
                x, y, w, h = cv2.boundingRect(c)
                out.append(Detection(
                    label="motion", score=min(1.0, area / 10000),
                    class_id=None, bbox=(float(x), float(y), float(w), float(h)),
                    attrs={"area": float(area)},
                ))
            return out

        detections = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            detections=detections, source_node=self.node_id)}
