"""Fall-detection heuristic — flag when the largest depth blob is wider than tall.

A standing person fills a tall, narrow column in the depth map. A fallen
person collapses into a short, wide blob. We pick the single largest
connected component in the configured depth band and gate on its bounding-box
aspect ratio (width / height) and minimum size.

This is a HEURISTIC, not a medical-grade fall detector. Real systems combine
this signal with motion history, time-on-floor confirmation, and ideally an
explicit "is the floor?" plane fit. Use this as one input to a fall pipeline,
not as the sole decision.
"""

from __future__ import annotations

from typing import Any

from ....pipeline.types import DepthFrame, Event, PortType
from ...node import Node, Port


class FallDetectionNode(Node):
    TYPE_ID = "condition.fall_detection"
    UI_CATEGORY = "condition"
    INPUTS = (Port("depth", PortType.DEPTH_FRAME),)
    OUTPUTS = (
        Port("match", PortType.EVENT, required=False),
        Port("no_match", PortType.EVENT, required=False),
    )
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "near_mm": {"type": "integer", "default": 500, "minimum": 0},
            "far_mm": {"type": "integer", "default": 4000, "minimum": 1},
            "min_blob_pixels": {"type": "integer", "default": 4000, "minimum": 1,
                                 "description": "Ignore blobs smaller than a person-sized region"},
            "aspect_ratio_threshold": {"type": "number", "default": 1.5, "minimum": 0.5,
                                        "description": "Trigger when width/height >= this"},
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        import cv2
        import numpy as np

        df: DepthFrame | None = inputs.get("depth")
        if df is None:
            return {}
        near = int(self.config.get("near_mm", 500))
        far = int(self.config.get("far_mm", 4000))
        if far <= near:
            return {}
        min_pix = int(self.config.get("min_blob_pixels", 4000))
        ar_thresh = float(self.config.get("aspect_ratio_threshold", 1.5))

        mask = ((df.data >= near) & (df.data <= far)).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
        n_lab, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        largest_idx = -1
        largest_area = 0
        for i in range(1, n_lab):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area > largest_area:
                largest_area = area
                largest_idx = i

        if largest_idx < 0 or largest_area < min_pix:
            return {"no_match": Event(
                pipeline_id=self.context.pipeline_id, node_id=self.node_id,
                camera_id=df.camera_id, timestamp_ns=df.timestamp_ns,
                kind="fall_detection",
                payload={"matched": False, "reason": "no_blob_above_min_size",
                          "largest_area_px": largest_area},
            )}

        x = int(stats[largest_idx, cv2.CC_STAT_LEFT])
        y = int(stats[largest_idx, cv2.CC_STAT_TOP])
        w = int(stats[largest_idx, cv2.CC_STAT_WIDTH])
        h = int(stats[largest_idx, cv2.CC_STAT_HEIGHT])
        aspect = w / max(1, h)
        matched = aspect >= ar_thresh

        evt = Event(
            pipeline_id=self.context.pipeline_id, node_id=self.node_id,
            camera_id=df.camera_id, timestamp_ns=df.timestamp_ns,
            kind="fall_detection",
            payload={
                "matched": matched,
                "blob": {"x": x, "y": y, "w": w, "h": h, "area_px": largest_area,
                          "aspect_ratio": round(aspect, 2)},
                "aspect_ratio_threshold": ar_thresh,
            },
        )
        if self.context.event_bus is not None:
            self.context.event_bus.publish_nowait(evt)
        return {"match": evt} if matched else {"no_match": evt}
