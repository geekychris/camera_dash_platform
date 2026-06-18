"""YOLO-World detector — open-vocabulary, text-prompted.

Unlike :class:`YoloDetectorNode` which is locked to YOLO's COCO labels
(person, dog, car, etc.), YOLO-World accepts an arbitrary list of class names
as text prompts at runtime. Use this for classes not in COCO (scorpion, drone,
PPE, manufacturing-defect labels, …).

The model file is auto-downloaded by Ultralytics on first use. Default is
``yolov8s-worldv2.pt`` (small + v2 weights); use ``yolov8x-worldv2.pt`` for
better recall on a GPU.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)


class YoloWorldDetectorNode(Node):
    """Open-vocabulary YOLO-World — detect arbitrary classes by text prompt."""

    TYPE_ID = "detector.yolo_world"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["classes"],
        "properties": {
            "model": {"type": "string", "default": "yolov8s-worldv2.pt",
                      "description": "yolov8{n,s,m,l,x}-worldv2.pt; auto-downloaded on first use"},
            "classes": {"type": "array", "items": {"type": "string"},
                        "minItems": 1,
                        "description": "Free-text class names (e.g. ['scorpion', 'drone', 'safety helmet'])"},
            "device": {"type": "string", "enum": ["cpu", "mps", "cuda"], "default": "cpu"},
            "conf": {"type": "number", "default": 0.1, "minimum": 0.0, "maximum": 1.0,
                     "description": "Open-vocab models need lower thresholds than COCO YOLO"},
            "iou": {"type": "number", "default": 0.45, "minimum": 0.0, "maximum": 1.0},
            "imgsz": {"type": "integer", "default": 640},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._model: Any = None
        self._classes: list[str] = []

    async def setup(self) -> None:
        from ultralytics import YOLO  # type: ignore

        model_name = self.config.get("model", "yolov8s-worldv2.pt")
        self._classes = list(self.config.get("classes") or [])
        if not self._classes:
            raise ValueError("detector.yolo_world requires at least one entry in `classes`")
        self._model = await asyncio.to_thread(YOLO, model_name)
        # Push the text prompts into the model — this is what makes it open-vocab.
        await asyncio.to_thread(self._model.set_classes, self._classes)
        log.info("yolo_world loaded %s on %s with classes=%s",
                 model_name, self.config.get("device", "cpu"), self._classes)

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        conf = float(self.config.get("conf", 0.1))
        iou = float(self.config.get("iou", 0.45))
        device = self.config.get("device", "cpu")
        imgsz = int(self.config.get("imgsz", 640))

        def _run() -> list[Detection]:
            results = self._model.predict(
                frame.data, conf=conf, iou=iou, device=device, imgsz=imgsz, verbose=False)
            out: list[Detection] = []
            for r in results:
                if r.boxes is None:
                    continue
                for box in r.boxes:
                    cls_id = int(box.cls.item())
                    # YOLO-World numbers classes in the order we set them
                    label = self._classes[cls_id] if cls_id < len(self._classes) else str(cls_id)
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
