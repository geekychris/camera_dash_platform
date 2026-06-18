"""OpenCV DNN detector — supports Caffe / TensorFlow / Darknet / ONNX via cv2.dnn."""

from __future__ import annotations

import asyncio
from typing import Any

import cv2

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port


class OpenCvDnnNode(Node):
    TYPE_ID = "detector.opencv_dnn"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["model_path"],
        "properties": {
            "model_path": {"type": "string"},
            "config_path": {"type": "string", "default": ""},
            "labels": {"type": "array", "items": {"type": "string"}, "default": []},
            "input_size": {"type": "integer", "default": 300},
            "scale": {"type": "number", "default": 0.00784313725},  # 1/127.5
            "mean": {"type": "array", "items": {"type": "number"},
                     "default": [127.5, 127.5, 127.5]},
            "swap_rb": {"type": "boolean", "default": True},
            "conf": {"type": "number", "default": 0.5},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._net: Any = None

    async def setup(self) -> None:
        m = self.config["model_path"]
        cfg = self.config.get("config_path") or ""
        self._net = await asyncio.to_thread(cv2.dnn.readNet, m, cfg)

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        size = int(self.config.get("input_size", 300))
        scale = float(self.config.get("scale", 1 / 127.5))
        mean = tuple(self.config.get("mean", [127.5, 127.5, 127.5]))
        swap = bool(self.config.get("swap_rb", True))
        conf_th = float(self.config.get("conf", 0.5))
        labels: list[str] = self.config.get("labels") or []

        def _run() -> list[Detection]:
            blob = cv2.dnn.blobFromImage(frame.data, scale, (size, size), mean, swap, False)
            self._net.setInput(blob)
            out = self._net.forward()
            # SSD-style output: (1, 1, N, 7) [_, _, conf, class, x1, y1, x2, y2]
            detections: list[Detection] = []
            h, w = frame.height, frame.width
            for i in range(out.shape[2]):
                conf = float(out[0, 0, i, 2])
                if conf < conf_th:
                    continue
                cls = int(out[0, 0, i, 1])
                x1, y1, x2, y2 = (float(out[0, 0, i, j]) for j in (3, 4, 5, 6))
                detections.append(Detection(
                    label=labels[cls] if cls < len(labels) else str(cls),
                    score=conf, class_id=cls,
                    bbox=(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h),
                ))
            return detections

        detections = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            detections=detections, source_node=self.node_id)}
