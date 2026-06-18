"""Luxonis OAK (OAK-D, OAK-1, OAK-D-Lite, OAK-D Pro) camera driver via DepthAI.

OAK cameras are USB stereo cameras with on-device neural inference. This driver
exposes their RGB stream as a normal :class:`Frame` source. Depth and on-device
inference are deferred to follow-up nodes (e.g. ``source.oak_depth``,
``detector.oak_yolo``) to keep this file small.

Spec params:
    mxid            device serial; auto-pick first OAK if omitted
    width/height    output resolution (default 1280x720, native sensor)
    fps             default 30
    color_order     "bgr" (default, matches the rest of camera_dash) or "rgb"

Requires the ``depthai`` package (``pip install depthai``). Not loaded eagerly
so the rest of the platform works without it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

import numpy as np

from ..pipeline.types import Frame, PixelFormat
from .base import Camera, CameraSpec

log = logging.getLogger(__name__)


class OakCamera(Camera):
    """RGB stream from a Luxonis OAK camera (OAK-D, OAK-1, etc.)."""

    def __init__(self, spec: CameraSpec, frame_bus: Any) -> None:
        super().__init__(spec, frame_bus)
        self._device: Any = None
        self._q_rgb: Any = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return
        try:
            import depthai as dai  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "depthai not installed — pip install depthai"
            ) from exc

        await asyncio.to_thread(self._open_device, dai)
        self._running = True
        self._task = asyncio.create_task(self._pull_loop(), name=f"oak/{self.id}")
        log.info("OAK camera %s started", self.id)

    def _open_device(self, dai: Any) -> None:
        p = self.spec.params
        w = int(p.get("width", 1280))
        h = int(p.get("height", 720))
        fps = int(p.get("fps", 30))
        # Build DepthAI pipeline: ColorCamera → XLinkOut (host queue)
        pipeline = dai.Pipeline()
        cam = pipeline.create(dai.node.ColorCamera)
        # Choose nearest sensor resolution
        if h <= 720:
            cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_720_P)
        elif h <= 800:
            cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_800_P)
        elif h <= 1080:
            cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
        else:
            cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_4_K)
        cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
        cam.setFps(fps)
        cam.setColorOrder(
            dai.ColorCameraProperties.ColorOrder.BGR
            if self.spec.params.get("color_order", "bgr").lower() == "bgr"
            else dai.ColorCameraProperties.ColorOrder.RGB
        )
        cam.setVideoSize(w, h)

        xout = pipeline.create(dai.node.XLinkOut)
        xout.setStreamName("rgb")
        cam.video.link(xout.input)

        mxid = p.get("mxid")
        if mxid:
            device_info = dai.DeviceInfo(mxid)
            self._device = dai.Device(pipeline, device_info)
        else:
            self._device = dai.Device(pipeline)
        self._q_rgb = self._device.getOutputQueue(name="rgb", maxSize=2, blocking=False)
        log.info("OAK %s opened on %s", self.id, self._device.getMxId())

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        if self._device is not None:
            try:
                await asyncio.to_thread(self._device.close)
            except Exception:  # pragma: no cover
                log.exception("error closing OAK device")
            self._device = None
            self._q_rgb = None
        log.info("OAK camera %s stopped", self.id)

    async def _pull_loop(self) -> None:
        try:
            while self._running:
                frame = await asyncio.to_thread(self._q_rgb.tryGet)
                if frame is None:
                    await asyncio.sleep(0.005)
                    continue
                arr: np.ndarray = frame.getCvFrame()  # already BGR HxWx3 uint8
                h, w = arr.shape[:2]
                self.frame_bus.publish_nowait(self.id, Frame(
                    camera_id=self.id, timestamp_ns=time.time_ns(),
                    width=w, height=h, pixel_format=PixelFormat.BGR, data=arr,
                ))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("OAK %s pull loop crashed", self.id)
