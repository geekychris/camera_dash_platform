"""``broadcast.snapshot`` — serve the latest frame as a JPEG over HTTP.

A lightweight alternative to ``broadcast.stream`` (which sets up a full
GStreamer/MediaMTX video pipeline). The snapshot node JPEG-encodes incoming
frames at a configurable rate and parks them in the snapshot registry; the
HTTP endpoint ``/api/broadcast/snapshot/<stream_id>.jpg`` serves the latest
bytes to any client (an `<img>` tag, OBS browser source, Grafana panel,
home-automation dashboard).

Stream id defaults to ``<pipeline>/<node>``; override with ``id`` in config
if you want a stable, human-readable URL (e.g. ``front_door_latest``).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ....pipeline.types import Frame, PortType
from ....streaming.snapshot_registry import SnapshotEntry
from ...node import Node, Port

log = logging.getLogger(__name__)


class SnapshotBroadcast(Node):
    TYPE_ID = "broadcast.snapshot"
    UI_CATEGORY = "broadcast"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "id": {
                "type": "string", "default": "",
                "description": "Stream id (URL slug). Empty = <pipeline_id>/<node_id>.",
            },
            "label": {"type": "string", "default": ""},
            "fps": {
                "type": "number", "default": 4.0, "minimum": 0.1, "maximum": 30.0,
                "description": "Max frames per second to JPEG-encode (server-side throttle).",
            },
            "jpeg_quality": {
                "type": "integer", "default": 80, "minimum": 1, "maximum": 100,
            },
            "max_width": {
                "type": "integer", "default": 0, "minimum": 0,
                "description": "Down-scale to this width before encoding. 0 = native.",
            },
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._stream_id: str = ""
        self._last_encode: float = 0.0
        self._registered = False

    async def setup(self) -> None:
        self._stream_id = (
            str(self.config.get("id") or "")
            or f"{self.context.pipeline_id}/{self.node_id}"
        )

    async def teardown(self) -> None:
        reg = getattr(self.context, "snapshots", None)
        if reg is not None:
            await reg.remove(self._stream_id)

    async def process(self, **inputs: Any) -> dict[str, Any]:
        import cv2

        frame: Frame | None = inputs.get("frame")
        if frame is None:
            return {}
        target_fps = float(self.config.get("fps", 4.0))
        if target_fps > 0:
            period = 1.0 / target_fps
            now = time.monotonic()
            if now - self._last_encode < period:
                return {}
            self._last_encode = now

        img = frame.data
        max_w = int(self.config.get("max_width", 0))
        if max_w and img.shape[1] > max_w:
            scale = max_w / img.shape[1]
            new_w = max_w
            new_h = max(1, int(img.shape[0] * scale))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        quality = int(self.config.get("jpeg_quality", 80))
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return {}

        reg = getattr(self.context, "snapshots", None)
        if reg is None:
            return {}
        entry = SnapshotEntry(
            id=self._stream_id,
            pipeline_id=self.context.pipeline_id,
            node_id=self.node_id,
            label=self.config.get("label") or self._stream_id,
            width=int(img.shape[1]),
            height=int(img.shape[0]),
            jpeg=bytes(buf),
        )
        await reg.update(entry)
        if not self._registered:
            log.info("broadcast.snapshot %s registered (%dx%d, quality=%d)",
                     self._stream_id, entry.width, entry.height, quality)
            self._registered = True
        return {}
