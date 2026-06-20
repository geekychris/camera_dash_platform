"""Attach per-detection distance from a co-registered ``DepthFrame``.

Inputs:
    ``detections`` — DetectionSet from any 2D detector (yolo, mediapipe, …)
    ``depth``      — DepthFrame from ``source.camera_depth``

For each detection bbox, reads the depth ROI, drops zeros (invalid), and
writes the median + nearest mm into the detection's ``attrs``. Downstream
annotators / sinks / MQTT events see distances "for free" — no new ML model.

If the detection and depth streams come from different resolutions
(e.g. detector ran on a 1280×720 color frame but depth is 640×480 Kinect),
bboxes are scaled to the depth grid by simple uniform scaling. Use only when
the two streams share an optical axis.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ....pipeline.types import DepthFrame, DetectionSet, PortType
from ...node import Node, Port


class EnrichWithDepthNode(Node):
    TYPE_ID = "transform.enrich_with_depth"
    UI_CATEGORY = "transform"
    INPUTS = (
        Port("detections", PortType.DETECTIONS),
        Port("depth", PortType.DEPTH_FRAME),
    )
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "shrink_pct": {
                "type": "number", "default": 20.0, "minimum": 0.0, "maximum": 49.0,
                "description": "Shrink each bbox by this % per side before sampling — avoids "
                               "sampling background pixels at the edges of a person box",
            },
            "min_valid_pixels": {
                "type": "integer", "default": 20, "minimum": 1,
                "description": "Need at least this many valid depth samples; otherwise leave the detection unmodified",
            },
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        dets: DetectionSet | None = inputs.get("detections")
        df: DepthFrame | None = inputs.get("depth")
        if dets is None or df is None:
            return {}
        shrink = float(self.config.get("shrink_pct", 20.0)) / 100.0
        min_valid = int(self.config.get("min_valid_pixels", 20))
        H, W = df.height, df.width
        # We don't know the source resolution the detector used unless every
        # bbox carries it. Detections store pixel coords matching the upstream
        # frame; assume that frame's aspect matches depth (laptop+kinect cases
        # are 16:9 vs 4:3 though, so we fit the bbox in by max ratio).
        for d in dets.detections:
            x, y, w, h = d.bbox
            # Bboxes in source coords — infer source size as max(bbox extent, observed range).
            # Cleanest fallback: if a bbox lies outside [0,W]×[0,H], rescale by the ratio
            # max(extent)/depth_extent. In typical configurations (same camera for color &
            # depth, e.g. Kinect) the two resolutions match.
            src_w = max(W, int(x + w))
            src_h = max(H, int(y + h))
            sx = W / src_w
            sy = H / src_h
            x_d = x * sx
            y_d = y * sy
            w_d = w * sx
            h_d = h * sy
            inset_x = w_d * shrink
            inset_y = h_d * shrink
            x1 = max(0, int(x_d + inset_x))
            y1 = max(0, int(y_d + inset_y))
            x2 = min(W, int(x_d + w_d - inset_x))
            y2 = min(H, int(y_d + h_d - inset_y))
            if x2 <= x1 or y2 <= y1:
                continue
            roi = df.data[y1:y2, x1:x2]
            valid = roi[roi > 0]
            if valid.size < min_valid:
                d.attrs["depth_status"] = "insufficient"
                continue
            d.attrs["median_mm"] = int(np.median(valid))
            d.attrs["nearest_mm"] = int(valid.min())
            d.attrs["depth_valid_pct"] = round(100.0 * valid.size / roi.size, 1)
        return {"detections": dets}
