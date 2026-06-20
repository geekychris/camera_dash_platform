"""Depth colormap — convert a ``DepthFrame`` (uint16 mm) into a ``Frame`` (BGR)
suitable for display tiles, derived streams, and standard 2D detectors.

Zeros in the depth map are "no reading" and get rendered as a fixed neutral
colour (default: black) so they don't drag the colormap range out to invalid
values. Everything else gets stretched into [near_mm, far_mm] and mapped
through an OpenCV colormap.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from ....pipeline.types import DepthFrame, Frame, PixelFormat, PortType
from ...node import Node, Port

_CV_COLORMAPS: dict[str, int] = {}


def _cv_colormap(name: str) -> int:
    import cv2
    if not _CV_COLORMAPS:
        _CV_COLORMAPS.update({
            "turbo": cv2.COLORMAP_TURBO,
            "viridis": cv2.COLORMAP_VIRIDIS,
            "inferno": cv2.COLORMAP_INFERNO,
            "magma": cv2.COLORMAP_MAGMA,
            "plasma": cv2.COLORMAP_PLASMA,
            "jet": cv2.COLORMAP_JET,
            "hot": cv2.COLORMAP_HOT,
            "bone": cv2.COLORMAP_BONE,
        })
    return _CV_COLORMAPS.get(name.lower(), cv2.COLORMAP_TURBO)


class DepthColormapNode(Node):
    """Colorize a depth map into a BGR frame.

    Use this in front of any node that wants ``Frame`` (e.g. ``sink.stream``,
    ``transform.annotate``, ``detector.yolo``) but the input is depth.
    """

    TYPE_ID = "transform.depth_colormap"
    UI_CATEGORY = "transform"
    INPUTS = (Port("depth", PortType.DEPTH_FRAME),)
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "near_mm": {"type": "integer", "default": 500, "minimum": 0,
                         "description": "Distance mapped to the start of the colormap"},
            "far_mm": {"type": "integer", "default": 4000, "minimum": 1,
                        "description": "Distance mapped to the end of the colormap"},
            "colormap": {"type": "string",
                          "enum": ["turbo", "viridis", "inferno", "magma", "plasma", "jet", "hot", "bone"],
                          "default": "turbo",
                          "description": "OpenCV colormap"},
            "invalid_bgr": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0, "maximum": 255},
                "minItems": 3, "maxItems": 3,
                "default": [0, 0, 0],
                "description": "BGR colour used for pixels with no depth reading",
            },
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        import cv2
        depth_frame: DepthFrame | None = inputs.get("depth")
        if depth_frame is None:
            return {}
        near = int(self.config.get("near_mm", 500))
        far = int(self.config.get("far_mm", 4000))
        if far <= near:
            far = near + 1
        cmap = _cv_colormap(str(self.config.get("colormap", "turbo")))
        invalid_bgr = self.config.get("invalid_bgr") or [0, 0, 0]

        data = depth_frame.data
        # Clip to [near, far], then stretch into [0, 255]. Invalid (zero)
        # pixels map to 0 by accident — we paint them over afterward.
        clipped = np.clip(data, near, far)
        scaled = ((clipped.astype(np.int32) - near) * 255 // (far - near)).astype(np.uint8)
        bgr = cv2.applyColorMap(scaled, cmap)
        invalid = data == 0
        if invalid.any():
            bgr[invalid] = np.asarray(invalid_bgr, dtype=np.uint8)

        out = Frame(
            camera_id=depth_frame.camera_id,
            timestamp_ns=depth_frame.timestamp_ns or time.time_ns(),
            width=depth_frame.width,
            height=depth_frame.height,
            pixel_format=PixelFormat.BGR,
            data=bgr,
            metadata={"colormap": str(self.config.get("colormap", "turbo")),
                       "near_mm": near, "far_mm": far},
        )
        return {"frame": out}
