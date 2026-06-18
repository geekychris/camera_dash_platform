"""MediaPipe pose detector — body landmarks + a simple fall heuristic.

Emits one :class:`Detection` per visible person with a synthetic ``label`` of
either ``"pose"`` or ``"pose:fallen"``. Fall heuristic: shoulder→ankle vector
mostly horizontal AND torso center in the lower half of the frame.

Attaches the raw 33 landmarks (normalized 0..1) in ``attrs["landmarks"]`` so
downstream nodes (custom plugins) can do richer pose analysis.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port


class PoseDetectorNode(Node):
    TYPE_ID = "detector.pose"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "model_complexity": {"type": "integer", "enum": [0, 1, 2], "default": 1,
                                  "description": "0=fastest, 2=most accurate"},
            "min_confidence": {"type": "number", "default": 0.5},
            "detect_fall": {"type": "boolean", "default": True,
                             "description": "Tag detections as 'pose:fallen' when heuristic fires"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._pose: Any = None

    async def setup(self) -> None:
        import mediapipe as mp  # type: ignore

        self._pose = mp.solutions.pose.Pose(
            model_complexity=int(self.config.get("model_complexity", 1)),
            min_detection_confidence=float(self.config.get("min_confidence", 0.5)),
        )

    async def teardown(self) -> None:
        if self._pose is not None:
            import contextlib
            with contextlib.suppress(Exception):
                self._pose.close()

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        detect_fall = bool(self.config.get("detect_fall", True))

        def _run() -> list[Detection]:
            import cv2

            rgb = cv2.cvtColor(frame.data, cv2.COLOR_BGR2RGB)
            res = self._pose.process(rgb)
            if not res.pose_landmarks:
                return []
            lms = res.pose_landmarks.landmark
            xs = [lm.x for lm in lms]
            ys = [lm.y for lm in lms]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            label = "pose"
            if detect_fall:
                # Heuristic: shoulder midpoint to ankle midpoint vector is more
                # horizontal than vertical, AND person sits in the lower half.
                ls, rs, la, ra = lms[11], lms[12], lms[27], lms[28]
                sx = (ls.x + rs.x) / 2
                sy = (ls.y + rs.y) / 2
                ax = (la.x + ra.x) / 2
                ay = (la.y + ra.y) / 2
                dx = abs(ax - sx)
                dy = abs(ay - sy)
                if dx > dy * 0.8 and sy > 0.45:
                    label = "pose:fallen"
            return [Detection(
                label=label, score=float(res.pose_landmarks.landmark[0].visibility or 0.5),
                bbox=(x1 * frame.width, y1 * frame.height,
                       (x2 - x1) * frame.width, (y2 - y1) * frame.height),
                attrs={"landmarks": [{"x": lm.x, "y": lm.y, "z": lm.z, "v": lm.visibility}
                                       for lm in lms]},
            )]

        dets = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            detections=dets, source_node=self.node_id)}
