"""OCR — crop upstream detections and read text inside each bbox.

For ALPR (license plates): chain after ``detector.yolo classes=['car']`` (or a
plate-specific detector) so we OCR only inside car bboxes. For arbitrary text
in the scene, leave ``crop_to_bboxes=false`` and OCR the whole frame.

Backed by EasyOCR (~600MB on first model download).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)


class OcrNode(Node):
    TYPE_ID = "detector.ocr"
    UI_CATEGORY = "detector"
    INPUTS = (
        Port("frame", PortType.FRAME),
        Port("detections", PortType.DETECTIONS, required=False),
    )
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "languages": {"type": "array", "items": {"type": "string"}, "default": ["en"]},
            "gpu": {"type": "boolean", "default": False},
            "crop_to_bboxes": {"type": "boolean", "default": True,
                                "description": "If true and detections are connected, OCR only inside each bbox"},
            "min_confidence": {"type": "number", "default": 0.4},
            "label_prefix": {"type": "string", "default": "text:"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._reader: Any = None

    async def setup(self) -> None:
        try:
            import easyocr  # type: ignore
        except ImportError as exc:
            raise RuntimeError("detector.ocr needs easyocr: pip install easyocr") from exc
        langs = self.config.get("languages") or ["en"]
        self._reader = await asyncio.to_thread(
            easyocr.Reader, langs, bool(self.config.get("gpu", False)))
        log.info("ocr loaded languages=%s", langs)

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        prefix = self.config.get("label_prefix", "text:")
        min_conf = float(self.config.get("min_confidence", 0.4))
        crop_to_bboxes = bool(self.config.get("crop_to_bboxes", True))
        upstream: DetectionSet | None = inputs.get("detections")

        def _run() -> list[Detection]:
            import cv2

            results: list[Detection] = []
            crops: list[tuple[Any, int, int]] = []  # (image, x_offset, y_offset)
            if crop_to_bboxes and upstream is not None and upstream.detections:
                for d in upstream.detections:
                    x, y, w, h = (int(v) for v in d.bbox)
                    x = max(0, x)
                    y = max(0, y)
                    crop = frame.data[y:y + h, x:x + w]
                    if crop.size > 0:
                        crops.append((crop, x, y))
            else:
                crops.append((frame.data, 0, 0))
            for img, ox, oy in crops:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                hits = self._reader.readtext(gray)
                for (poly, text, conf) in hits:
                    if conf < min_conf or not text.strip():
                        continue
                    xs = [p[0] for p in poly]
                    ys = [p[1] for p in poly]
                    x1, x2 = min(xs), max(xs)
                    y1, y2 = min(ys), max(ys)
                    results.append(Detection(
                        label=f"{prefix}{text.strip()}",
                        score=float(conf), class_id=None,
                        bbox=(float(x1 + ox), float(y1 + oy),
                               float(x2 - x1), float(y2 - y1)),
                        attrs={"text": text.strip()},
                    ))
            return results

        dets = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            detections=dets, source_node=self.node_id)}
