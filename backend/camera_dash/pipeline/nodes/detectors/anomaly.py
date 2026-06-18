"""Background-modelling anomaly detector — flag novel/large blobs.

Extends MOG2 with a "novelty" mode: emits a single detection per cluster of
significant change, with a "novelty score" = blob area / largest historical
blob area. Useful for "something is here that wasn't here before".

Less precise than a trained model but no labels needed and works on FLIR.
"""

from __future__ import annotations

import asyncio
from typing import Any

import cv2

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port


class AnomalyNode(Node):
    TYPE_ID = "detector.anomaly"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "history": {"type": "integer", "default": 1000,
                         "description": "Frames of history for the background model"},
            "var_threshold": {"type": "number", "default": 30},
            "min_area": {"type": "integer", "default": 1500,
                          "description": "Smallest blob worth reporting (pixels²)"},
            "warmup_frames": {"type": "integer", "default": 50,
                               "description": "Suppress emissions until BG model has seen this many frames"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._bg: Any = None
        self._n_seen = 0
        self._max_area_seen = 1.0

    async def setup(self) -> None:
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=int(self.config.get("history", 1000)),
            varThreshold=float(self.config.get("var_threshold", 30)),
            detectShadows=False,
        )

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        min_area = int(self.config.get("min_area", 1500))
        warmup = int(self.config.get("warmup_frames", 50))

        def _run() -> list[Detection]:
            self._n_seen += 1
            mask = self._bg.apply(frame.data)
            _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
            if self._n_seen < warmup:
                return []
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            out: list[Detection] = []
            for c in contours:
                area = cv2.contourArea(c)
                if area < min_area:
                    continue
                if area > self._max_area_seen:
                    self._max_area_seen = area
                x, y, w, h = cv2.boundingRect(c)
                novelty = min(1.0, area / max(1.0, self._max_area_seen))
                out.append(Detection(
                    label="anomaly", score=float(novelty), class_id=None,
                    bbox=(float(x), float(y), float(w), float(h)),
                    attrs={"area": float(area), "novelty": float(novelty)},
                ))
            return out

        dets = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            detections=dets, source_node=self.node_id)}
