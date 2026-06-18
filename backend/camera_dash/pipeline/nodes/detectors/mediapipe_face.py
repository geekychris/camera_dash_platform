"""MediaPipe face detector."""

from __future__ import annotations

import asyncio
from typing import Any

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port


class MediapipeFaceNode(Node):
    TYPE_ID = "detector.mediapipe"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "model_selection": {"type": "integer", "enum": [0, 1], "default": 0,
                                "description": "0 = short-range (≤2m), 1 = full-range (≤5m)"},
            "min_confidence": {"type": "number", "default": 0.5},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._detector: Any = None

    async def setup(self) -> None:
        import mediapipe as mp  # type: ignore

        self._detector = mp.solutions.face_detection.FaceDetection(
            model_selection=int(self.config.get("model_selection", 0)),
            min_detection_confidence=float(self.config.get("min_confidence", 0.5)),
        )

    async def teardown(self) -> None:
        if self._detector is not None:
            import contextlib
            with contextlib.suppress(Exception):  # pragma: no cover
                self._detector.close()

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}

        def _run() -> list[Detection]:
            import cv2

            rgb = cv2.cvtColor(frame.data, cv2.COLOR_BGR2RGB)
            res = self._detector.process(rgb)
            if not res.detections:
                return []
            h, w = frame.height, frame.width
            out: list[Detection] = []
            for d in res.detections:
                rb = d.location_data.relative_bounding_box
                out.append(Detection(
                    label="face",
                    score=float(d.score[0]) if d.score else 0.0,
                    class_id=0,
                    bbox=(rb.xmin * w, rb.ymin * h, rb.width * w, rb.height * h),
                ))
            return out

        detections = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            detections=detections, source_node=self.node_id)}
