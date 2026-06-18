"""YOLOv8 segmentation — pixel-accurate instance masks.

Same labels as YOLO COCO, but each :class:`Detection` carries a binary mask in
``attrs["mask"]`` (uint8 0/255, same shape as the frame). Useful for crops,
counting pixels, privacy masking specific instances.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)


class SegmentationNode(Node):
    TYPE_ID = "detector.segmentation"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "model": {"type": "string", "default": "yolov8n-seg.pt",
                       "description": "Any YOLOv8 segmentation weight: n/s/m/l/x-seg.pt"},
            "device": {"type": "string", "enum": ["cpu", "mps", "cuda"], "default": "cpu"},
            "conf": {"type": "number", "default": 0.25},
            "classes": {"type": "array", "items": {"type": "string"}, "default": []},
            "include_masks": {"type": "boolean", "default": True,
                              "description": "Disable to save memory if downstream doesn't need pixel masks"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._model: Any = None

    async def setup(self) -> None:
        from ultralytics import YOLO  # type: ignore

        model_name = self.config.get("model", "yolov8n-seg.pt")
        self._model = await asyncio.to_thread(YOLO, model_name)
        log.info("segmentation loaded %s on %s", model_name, self.config.get("device", "cpu"))

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        keep = set(self.config.get("classes") or [])
        include_masks = bool(self.config.get("include_masks", True))

        def _run() -> list[Detection]:
            results = self._model.predict(
                frame.data, conf=float(self.config.get("conf", 0.25)),
                device=self.config.get("device", "cpu"), verbose=False)
            out: list[Detection] = []
            for r in results:
                if r.boxes is None or r.masks is None:
                    continue
                names = r.names
                for i, box in enumerate(r.boxes):
                    cls_id = int(box.cls.item())
                    label = names.get(cls_id, str(cls_id))
                    if keep and label not in keep:
                        continue
                    x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
                    attrs: dict[str, Any] = {}
                    if include_masks:
                        m = r.masks.data[i].cpu().numpy()
                        # Mask may be at model resolution; resize to frame
                        if m.shape != (frame.height, frame.width):
                            import cv2
                            m = cv2.resize(m, (frame.width, frame.height),
                                            interpolation=cv2.INTER_NEAREST)
                        attrs["mask"] = (m > 0.5).astype(np.uint8) * 255
                    out.append(Detection(
                        label=label, score=float(box.conf.item()), class_id=cls_id,
                        bbox=(x1, y1, x2 - x1, y2 - y1), attrs=attrs,
                    ))
            return out

        dets = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            detections=dets, source_node=self.node_id)}
