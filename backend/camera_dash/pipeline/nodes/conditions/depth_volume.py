"""Depth volume gate — match when ``min_blobs`` distinct objects of at least
``min_blob_pixels`` each are present within a [near_mm, far_mm] band.

More selective than ``condition.distance_gate``: that one only checks total
coverage in the band, so a single outstretched hand at the right distance can
trigger it. ``depth_volume`` runs connected-components on the in-band mask
and counts how many real "things" are there.
"""

from __future__ import annotations

from typing import Any

from ....pipeline.types import DepthFrame, Event, PortType
from ...node import Node, Port


class DepthVolumeNode(Node):
    TYPE_ID = "condition.depth_volume"
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
            "far_mm": {"type": "integer", "default": 2500, "minimum": 1},
            "min_blob_pixels": {"type": "integer", "default": 1500, "minimum": 1,
                                 "description": "Smallest connected region counted as a 'thing'"},
            "min_blobs": {"type": "integer", "default": 1, "minimum": 1, "maximum": 64,
                          "description": "Trigger when at least this many blobs are present"},
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        import cv2
        import numpy as np

        df: DepthFrame | None = inputs.get("depth")
        if df is None:
            return {}
        near = int(self.config.get("near_mm", 500))
        far = int(self.config.get("far_mm", 2500))
        if far <= near:
            return {}
        min_pix = int(self.config.get("min_blob_pixels", 1500))
        min_blobs = int(self.config.get("min_blobs", 1))

        data = df.data
        mask = ((data >= near) & (data <= far)).astype(np.uint8) * 255
        # Smooth out pinhole noise from IR shadow flicker.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
        n_lab, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        blobs: list[dict[str, int]] = []
        for i in range(1, n_lab):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < min_pix:
                continue
            blobs.append({
                "area_px": area,
                "x": int(stats[i, cv2.CC_STAT_LEFT]),
                "y": int(stats[i, cv2.CC_STAT_TOP]),
                "w": int(stats[i, cv2.CC_STAT_WIDTH]),
                "h": int(stats[i, cv2.CC_STAT_HEIGHT]),
            })
        blobs.sort(key=lambda b: b["area_px"], reverse=True)
        matched = len(blobs) >= min_blobs
        evt = Event(
            pipeline_id=self.context.pipeline_id,
            node_id=self.node_id,
            camera_id=df.camera_id,
            timestamp_ns=df.timestamp_ns,
            kind="depth_volume",
            payload={
                "near_mm": near, "far_mm": far,
                "min_blob_pixels": min_pix, "min_blobs": min_blobs,
                "blob_count": len(blobs),
                "blobs": blobs[:8],
                "matched": matched,
            },
        )
        if self.context.event_bus is not None:
            self.context.event_bus.publish_nowait(evt)
        return {"match": evt} if matched else {"no_match": evt}
