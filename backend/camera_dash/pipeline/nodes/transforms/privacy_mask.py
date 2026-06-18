"""Privacy mask — blur a polygon region (whole frame) or matching detections.

Mode ``polygon``: blur everything inside the polygon (e.g. neighbor's window).
Mode ``detections``: blur the bbox of each detection (e.g. all faces). Pair
with ``detector.mediapipe`` for face blur, or ``detector.yolo classes=['person']``
to anonymize people.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from ....pipeline.types import DetectionSet, Frame, PortType
from ...node import Node, Port


class PrivacyMaskNode(Node):
    TYPE_ID = "transform.privacy_mask"
    UI_CATEGORY = "transform"
    INPUTS = (
        Port("frame", PortType.FRAME),
        Port("detections", PortType.DETECTIONS, required=False),
    )
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["polygon", "detections", "both"],
                      "default": "polygon"},
            "polygon": {"type": "array",
                         "items": {"type": "array", "items": {"type": "number"},
                                    "minItems": 2, "maxItems": 2},
                         "default": [],
                         "description": "Pixel coords; used when mode includes 'polygon'"},
            "classes": {"type": "array", "items": {"type": "string"}, "default": [],
                         "description": "Only mask these labels (empty = all)"},
            "blur_kernel": {"type": "integer", "default": 41, "minimum": 5,
                             "description": "Odd; bigger = blurrier"},
            "method": {"type": "string", "enum": ["blur", "pixelate", "solid"],
                        "default": "blur"},
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        dets: DetectionSet | None = inputs.get("detections")
        mode = self.config.get("mode", "polygon")
        method = self.config.get("method", "blur")
        kernel = int(self.config.get("blur_kernel", 41))
        if kernel % 2 == 0:
            kernel += 1

        img = frame.data.copy()
        h, w = img.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)

        if mode in ("polygon", "both") and self.config.get("polygon"):
            pts = np.array(self.config["polygon"], dtype=np.int32)
            cv2.fillPoly(mask, [pts], 255)

        if mode in ("detections", "both") and dets is not None:
            keep = set(self.config.get("classes") or [])
            for d in dets.detections:
                if keep and d.label not in keep:
                    continue
                # Prefer instance mask if present (segmentation node), else bbox
                if d.attrs and isinstance(d.attrs.get("mask"), np.ndarray):
                    m = d.attrs["mask"]
                    mask = np.maximum(mask, m if m.shape == mask.shape else
                                       cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST))
                else:
                    x, y, bw, bh = (int(v) for v in d.bbox)
                    cv2.rectangle(mask, (max(0, x), max(0, y)),
                                   (min(w, x + bw), min(h, y + bh)), 255, -1)

        if mask.any():
            if method == "blur":
                blurred = cv2.GaussianBlur(img, (kernel, kernel), 0)
                img = np.where(mask[..., None] > 0, blurred, img)
            elif method == "pixelate":
                small = cv2.resize(img, (max(1, w // kernel), max(1, h // kernel)),
                                    interpolation=cv2.INTER_LINEAR)
                pix = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
                img = np.where(mask[..., None] > 0, pix, img)
            else:  # solid
                img[mask > 0] = (32, 32, 32)

        return {"frame": Frame(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            width=frame.width, height=frame.height, pixel_format=frame.pixel_format,
            data=img, radiometric=frame.radiometric, metadata=frame.metadata,
        )}
