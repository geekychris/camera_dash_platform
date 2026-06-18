"""Apply an OpenCV colormap (mostly for thermal display)."""

from __future__ import annotations

from typing import Any

import cv2

from ....pipeline.types import Frame, PixelFormat, PortType
from ....utils.radiometric import normalize_for_display
from ...node import Node, Port

_COLORMAPS = {
    "inferno": cv2.COLORMAP_INFERNO, "jet": cv2.COLORMAP_JET,
    "hot": cv2.COLORMAP_HOT, "viridis": cv2.COLORMAP_VIRIDIS,
    "magma": cv2.COLORMAP_MAGMA, "plasma": cv2.COLORMAP_PLASMA,
    "turbo": cv2.COLORMAP_TURBO,
}


class ColormapNode(Node):
    TYPE_ID = "transform.colormap"
    UI_CATEGORY = "transform"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "colormap": {"type": "string", "enum": list(_COLORMAPS.keys()),
                         "default": "inferno"},
            "source": {"type": "string", "enum": ["data", "radiometric"], "default": "data",
                       "description": "Which channel to colorize: pixel data or radiometric matrix"},
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        cmap = _COLORMAPS[self.config.get("colormap", "inferno")]
        if self.config.get("source") == "radiometric" and frame.radiometric is not None:
            gray = normalize_for_display(frame.radiometric)
        else:
            gray = cv2.cvtColor(frame.data, cv2.COLOR_BGR2GRAY) if frame.data.ndim == 3 else frame.data
        bgr = cv2.applyColorMap(gray, cmap)
        return {"frame": Frame(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            width=frame.width, height=frame.height,
            pixel_format=PixelFormat.BGR, data=bgr,
            radiometric=frame.radiometric, metadata=frame.metadata,
        )}
