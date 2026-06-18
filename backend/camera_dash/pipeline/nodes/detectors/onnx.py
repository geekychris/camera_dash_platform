"""Generic ONNX Runtime detector — any model that fits the YOLO output convention.

Accepts NMS-included models or raw outputs; configurable via `output_format`.
For arbitrary architectures use the OpenCV DNN node or a custom plugin.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import cv2
import numpy as np

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)


class OnnxDetectorNode(Node):
    TYPE_ID = "detector.onnx"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["model_path"],
        "properties": {
            "model_path": {"type": "string", "description": "Path to .onnx file"},
            "providers": {"type": "array", "items": {"type": "string"},
                          "default": ["CPUExecutionProvider"]},
            "input_size": {"type": "integer", "default": 640},
            "labels": {"type": "array", "items": {"type": "string"}, "default": []},
            "conf": {"type": "number", "default": 0.25},
            "output_format": {"type": "string", "enum": ["yolov8"], "default": "yolov8"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._sess: Any = None
        self._input_name: str = ""

    async def setup(self) -> None:
        import onnxruntime as ort  # type: ignore

        providers = self.config.get("providers") or ["CPUExecutionProvider"]
        self._sess = await asyncio.to_thread(
            ort.InferenceSession, self.config["model_path"], None, providers)
        self._input_name = self._sess.get_inputs()[0].name
        log.info("onnx loaded %s with %s", self.config["model_path"], providers)

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        size = int(self.config.get("input_size", 640))
        labels: list[str] = self.config.get("labels") or []
        conf_th = float(self.config.get("conf", 0.25))

        def _run() -> list[Detection]:
            img = cv2.resize(frame.data, (size, size))
            blob = img.astype(np.float32) / 255.0
            blob = np.transpose(blob, (2, 0, 1))[None, ...]
            out = self._sess.run(None, {self._input_name: blob})[0]
            return _parse_yolov8(out, conf_th, labels, frame.width, frame.height, size)

        detections = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            detections=detections, source_node=self.node_id)}


def _parse_yolov8(out: np.ndarray, conf_th: float, labels: list[str],
                  orig_w: int, orig_h: int, size: int) -> list[Detection]:
    # YOLOv8 ONNX shape: (1, 4+nc, N). Transpose to (N, 4+nc).
    arr = out[0].T if out.ndim == 3 else out
    boxes = arr[:, :4]
    scores = arr[:, 4:]
    sx, sy = orig_w / size, orig_h / size
    results: list[Detection] = []
    for i in range(arr.shape[0]):
        cls_id = int(np.argmax(scores[i]))
        score = float(scores[i, cls_id])
        if score < conf_th:
            continue
        cx, cy, w, h = boxes[i]
        x = (cx - w / 2) * sx
        y = (cy - h / 2) * sy
        results.append(Detection(
            label=labels[cls_id] if cls_id < len(labels) else str(cls_id),
            score=score, class_id=cls_id, bbox=(float(x), float(y), float(w * sx), float(h * sy)),
        ))
    return results
