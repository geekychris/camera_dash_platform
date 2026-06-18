"""Dense optical flow (Farneback) — emits a magnitude event when the scene moves."""

from __future__ import annotations

import asyncio
from typing import Any

import cv2
import numpy as np

from ....pipeline.types import DetectionSet, Frame, PortType
from ...node import Node, Port


class OpticalFlowNode(Node):
    TYPE_ID = "detector.optical_flow"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "pyr_scale": {"type": "number", "default": 0.5},
            "levels": {"type": "integer", "default": 3},
            "winsize": {"type": "integer", "default": 15},
            "iterations": {"type": "integer", "default": 3},
            "magnitude_threshold": {"type": "number", "default": 2.0,
                                    "description": "Emit only when mean magnitude exceeds this"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._prev: np.ndarray | None = None

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}

        def _run() -> DetectionSet:
            from ....pipeline.types import Detection

            gray = cv2.cvtColor(frame.data, cv2.COLOR_BGR2GRAY)
            empty = DetectionSet(camera_id=frame.camera_id,
                                 timestamp_ns=frame.timestamp_ns,
                                 source_node=self.node_id)
            if self._prev is None:
                self._prev = gray
                return empty
            flow = cv2.calcOpticalFlowFarneback(
                self._prev, gray, None,
                float(self.config.get("pyr_scale", 0.5)),
                int(self.config.get("levels", 3)),
                int(self.config.get("winsize", 15)),
                int(self.config.get("iterations", 3)),
                5, 1.2, 0,
            )
            self._prev = gray
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            mean_mag = float(mag.mean())
            if mean_mag < float(self.config.get("magnitude_threshold", 2.0)):
                return empty
            empty.detections.append(Detection(
                label="motion_flow", score=min(1.0, mean_mag / 10.0),
                bbox=(0.0, 0.0, float(frame.width), float(frame.height)),
                attrs={"mean_magnitude": mean_mag},
            ))
            return empty

        result = await asyncio.to_thread(_run)
        return {"detections": result}
