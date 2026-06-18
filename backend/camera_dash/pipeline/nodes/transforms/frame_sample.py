"""Frame-sample node — forward frames at most ``target_fps`` per second.

Drops intermediate frames synchronously (no buffering, no backpressure) so an
expensive downstream node (e.g. an open-vocab detector at imgsz>=1280) only
sees a fraction of the camera's natural frame rate. Put it on the branch you
want to rate-limit; parallel branches keep receiving every frame.
"""

from __future__ import annotations

import time
from typing import Any

from ....pipeline.types import Frame, PortType
from ...node import Node, Port


class FrameSampleNode(Node):
    TYPE_ID = "transform.frame_sample"
    UI_CATEGORY = "transform"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "target_fps": {
                "type": "number",
                "default": 2.0,
                "minimum": 0.01,
                "maximum": 60.0,
                "description": "Maximum frames-per-second to forward. Extra frames are dropped.",
            },
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._last = 0.0

    async def process(self, **inputs: Any) -> dict[str, Any]:
        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        target_fps = float(self.config.get("target_fps", 2.0))
        period = 1.0 / target_fps
        now = time.monotonic()
        if now - self._last < period:
            return {}
        self._last = now
        return {"frame": frame}
