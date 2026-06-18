"""Ultralytics YOLO detector — supports mps / cuda / cpu via device config."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)


class YoloDetectorNode(Node):
    """Run an Ultralytics YOLO model on incoming frames."""

    TYPE_ID = "detector.yolo"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "model": {"type": "string", "default": "yolov8n.pt",
                      "description": ".pt or .onnx; auto-downloaded if name is a known weight"},
            "device": {"type": "string", "enum": ["cpu", "mps", "cuda"], "default": "cpu"},
            "conf": {"type": "number", "default": 0.25, "minimum": 0.0, "maximum": 1.0},
            "iou": {"type": "number", "default": 0.45, "minimum": 0.0, "maximum": 1.0},
            "classes": {"type": "array", "items": {"type": "string"}, "default": [],
                        "description": "If non-empty, only emit detections with these labels"},
            "imgsz": {"type": "integer", "default": 640},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._model: Any = None

    async def setup(self) -> None:
        from ultralytics import YOLO  # type: ignore

        model_name = self.config.get("model", "yolov8n.pt")
        self._model = await asyncio.to_thread(YOLO, model_name)
        log.info("yolo loaded %s on %s", model_name, self.config.get("device", "cpu"))

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        conf = float(self.config.get("conf", 0.25))
        iou = float(self.config.get("iou", 0.45))
        device = self.config.get("device", "cpu")
        imgsz = int(self.config.get("imgsz", 640))
        keep = set(self.config.get("classes") or [])

        def _run() -> list[Detection]:
            results = self._model.predict(
                frame.data, conf=conf, iou=iou, device=device, imgsz=imgsz, verbose=False)
            out: list[Detection] = []
            for r in results:
                names = r.names
                if r.boxes is None:
                    continue
                for box in r.boxes:
                    cls_id = int(box.cls.item())
                    label = names.get(cls_id, str(cls_id))
                    if keep and label not in keep:
                        continue
                    score = float(box.conf.item())
                    x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
                    out.append(Detection(
                        label=label, score=score, class_id=cls_id,
                        bbox=(x1, y1, x2 - x1, y2 - y1),
                    ))
            return out

        detections = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            detections=detections, source_node=self.node_id,
        )}
