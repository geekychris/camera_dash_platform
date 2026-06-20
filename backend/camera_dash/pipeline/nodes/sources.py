"""Source nodes — entry points into a pipeline. Override run() because they
have no inputs to read in a tick.
"""

from __future__ import annotations

import asyncio
import logging
import time

import cv2

from ...pipeline.types import Frame, PixelFormat
from ..node import Inbox, Node, Outbox, Port
from ..types import PortType

log = logging.getLogger(__name__)


class CameraSourceNode(Node):
    """Subscribes to a camera on the FrameBus and emits frames."""

    TYPE_ID = "source.camera"
    UI_CATEGORY = "source"
    INPUTS = ()
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["camera_id"],
        "properties": {
            "camera_id": {"type": "string", "title": "Camera ID"},
            "queue_depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 8},
        },
    }

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        camera_id = self.config["camera_id"]
        depth = int(self.config.get("queue_depth", 2))
        bus = self.context.frame_bus
        q = await bus.subscribe(camera_id, depth=depth)
        try:
            while True:
                frame = await q.get()
                await outbox.publish({"frame": frame})
        finally:
            await bus.unsubscribe(camera_id, q)


class CameraDepthSourceNode(Node):
    """Subscribes to the depth channel of a camera and emits ``DepthFrame``s.

    Only depth-capable cameras (Kinect, OAK-D with depth enabled, etc.)
    publish on this channel — for a UVC webcam the queue stays empty forever.
    Pair with ``source.camera`` if a pipeline needs both the color preview
    and aligned depth.
    """

    TYPE_ID = "source.camera_depth"
    UI_CATEGORY = "source"
    INPUTS = ()
    OUTPUTS = (Port("depth", PortType.DEPTH_FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["camera_id"],
        "properties": {
            "camera_id": {"type": "string", "title": "Camera ID",
                          "description": "Must be a depth-capable camera (kinect_v1, oak with depth)"},
            "queue_depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 8},
        },
    }

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        camera_id = self.config["camera_id"]
        depth = int(self.config.get("queue_depth", 2))
        bus = self.context.frame_bus
        q = await bus.subscribe_depth(camera_id, depth=depth)
        try:
            while True:
                df = await q.get()
                await outbox.publish({"depth": df})
        finally:
            await bus.unsubscribe_depth(camera_id, q)


class FileSourceNode(Node):
    """Reads frames from a video file (for testing pipelines without hardware)."""

    TYPE_ID = "source.file"
    UI_CATEGORY = "source"
    INPUTS = ()
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string", "title": "Video file path"},
            "camera_id": {"type": "string", "default": "file", "title": "Reported camera_id"},
            "loop": {"type": "boolean", "default": True},
            "fps": {"type": "integer", "default": 30},
        },
    }

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        path = self.config["path"]
        camera_id = self.config.get("camera_id", "file")
        loop = bool(self.config.get("loop", True))
        target_fps = int(self.config.get("fps", 30))
        period = 1.0 / target_fps

        while True:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                raise RuntimeError(f"could not open video: {path}")
            try:
                while True:
                    ok, frame_bgr = await asyncio.to_thread(cap.read)
                    if not ok:
                        break
                    h, w = frame_bgr.shape[:2]
                    fr = Frame(
                        camera_id=camera_id, timestamp_ns=time.time_ns(),
                        width=w, height=h, pixel_format=PixelFormat.BGR, data=frame_bgr,
                    )
                    await outbox.publish({"frame": fr})
                    await asyncio.sleep(period)
            finally:
                cap.release()
            if not loop:
                return
