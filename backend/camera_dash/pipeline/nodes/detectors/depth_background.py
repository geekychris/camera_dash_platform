"""Depth background subtraction — learn an empty-scene baseline, emit detections for foreground blobs.

Use this with a depth-capable camera (Kinect, OAK-D depth) when colour-domain
motion detectors (MOG2, optical flow) are too jumpy: depth is immune to
lighting, shadows, sun changes, and pet-vs-person colour overlap.

How it works:
    1. ``warmup_frames`` frames are buffered as the camera looks at an empty
       scene. The per-pixel median across those frames becomes the baseline.
    2. After warmup, every incoming frame is compared to the baseline.
       Pixels at least ``foreground_mm`` closer than baseline form the
       foreground mask. Invalid (0) pixels in either frame are ignored.
    3. Connected components are extracted; each blob ≥ ``min_blob_pixels``
       becomes a :class:`Detection` with bbox + median distance in attrs.

The baseline can be re-learned at runtime by feeding the node a ``reset``
trigger (TBD — for now, restart the pipeline to relearn).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ....pipeline.types import DepthFrame, Detection, DetectionSet, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)


class DepthBackgroundNode(Node):
    TYPE_ID = "detector.depth_background"
    UI_CATEGORY = "detector"
    INPUTS = (Port("depth", PortType.DEPTH_FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "warmup_frames": {"type": "integer", "default": 60, "minimum": 1, "maximum": 600,
                              "description": "Number of frames to average for the baseline"},
            "foreground_mm": {"type": "integer", "default": 150, "minimum": 10,
                              "description": "Pixels at least this many mm closer than baseline are foreground"},
            "max_distance_mm": {"type": "integer", "default": 6000, "minimum": 100,
                                 "description": "Ignore baseline pixels farther than this (Kinect ~4–5 m reliable)"},
            "min_blob_pixels": {"type": "integer", "default": 800, "minimum": 1,
                                 "description": "Smallest connected component reported as a detection"},
            "max_blobs": {"type": "integer", "default": 8, "minimum": 1, "maximum": 64,
                          "description": "Cap on detections per frame to avoid runaway clutter events"},
            "label": {"type": "string", "default": "foreground",
                      "description": "Label written into each detection"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._warmup_buf: list[np.ndarray] = []
        self._baseline: np.ndarray | None = None
        self._baseline_valid: np.ndarray | None = None  # mask of usable baseline pixels

    async def process(self, **inputs: Any) -> dict[str, Any]:
        import cv2
        df: DepthFrame | None = inputs.get("depth")
        if df is None:
            return {}
        warmup_n = int(self.config.get("warmup_frames", 60))
        fg_mm = int(self.config.get("foreground_mm", 150))
        max_d = int(self.config.get("max_distance_mm", 6000))
        min_pix = int(self.config.get("min_blob_pixels", 800))
        max_blobs = int(self.config.get("max_blobs", 8))
        label = str(self.config.get("label", "foreground"))

        cur = df.data
        if self._baseline is None:
            self._warmup_buf.append(cur.copy())
            if len(self._warmup_buf) >= warmup_n:
                stack = np.stack(self._warmup_buf, axis=0)
                # Treat 0 (no reading) as missing rather than near. Median over
                # only the valid samples per pixel is more robust than np.median
                # of the raw stack which would let 0s pull the baseline down.
                valid = stack > 0
                # Convert 0s to a large sentinel so they sort to the tail of the
                # sorted axis; the median then picks from the valid portion as
                # long as more than half were valid.
                stack_filled = np.where(valid, stack, np.iinfo(np.uint16).max)
                baseline = np.median(stack_filled, axis=0).astype(np.uint16)
                baseline_valid = valid.sum(axis=0) >= (warmup_n // 2)
                # Pixels with too-distant or never-seen baselines aren't usable.
                baseline_valid &= baseline > 0
                baseline_valid &= baseline <= max_d
                self._baseline = baseline
                self._baseline_valid = baseline_valid
                self._warmup_buf = []  # release memory
                log.info("depth_background %s: baseline learned (%d valid px / %d)",
                         self.node_id, int(baseline_valid.sum()), baseline.size)
            return {}

        assert self._baseline is not None and self._baseline_valid is not None
        # Foreground = pixel valid AND baseline valid AND (baseline - cur) >= fg_mm.
        cur_valid = cur > 0
        # int32 to allow safe subtraction; uint16 would underflow.
        diff = self._baseline.astype(np.int32) - cur.astype(np.int32)
        mask = (diff >= fg_mm) & cur_valid & self._baseline_valid
        mask_u8 = mask.astype(np.uint8) * 255
        # Light morphological clean-up to drop salt-and-pepper IR shadow flicker.
        mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN,
                                   cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))

        n_lab, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
        dets: list[Detection] = []
        for i in range(1, n_lab):  # skip background label 0
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < min_pix:
                continue
            x = int(stats[i, cv2.CC_STAT_LEFT])
            y = int(stats[i, cv2.CC_STAT_TOP])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            roi = cur[y:y + h, x:x + w]
            roi_valid = roi[(roi > 0) & mask[y:y + h, x:x + w]]
            median_mm = int(np.median(roi_valid)) if roi_valid.size else 0
            nearest_mm = int(roi_valid.min()) if roi_valid.size else 0
            cy, cx = centroids[i]
            dets.append(Detection(
                label=label,
                score=min(1.0, area / max(1.0, df.width * df.height * 0.25)),
                bbox=(float(x), float(y), float(w), float(h)),
                attrs={
                    "median_mm": median_mm,
                    "nearest_mm": nearest_mm,
                    "centroid": [float(cx), float(cy)],
                    "area_px": area,
                },
            ))
        # Cap to max_blobs by area so a noisy frame can't flood downstream.
        dets.sort(key=lambda d: d.attrs.get("area_px", 0), reverse=True)
        dets = dets[:max_blobs]
        return {"detections": DetectionSet(
            camera_id=df.camera_id, timestamp_ns=df.timestamp_ns,
            detections=dets, source_node=self.node_id,
        )}
