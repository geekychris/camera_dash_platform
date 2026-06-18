"""Desktop/screen capture as a virtual camera.

Useful for testing pipelines without aiming a real camera, or for monitoring a
window/dashboard. Supports macOS (``avfvideosrc capture-screen=true``) and
Linux X11 (``ximagesrc``).

Spec params:
    display_id      macOS screen index (0=main); Linux: ignored
    crop_x/y/w/h    optional crop region (whole screen if omitted)
    fps             default 15
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import platform
import time
from typing import Any

import numpy as np

from ..pipeline.types import Frame, PixelFormat
from .base import Camera, CameraSpec

log = logging.getLogger(__name__)


def _build_pipeline(spec: CameraSpec) -> str:
    p = spec.params
    fps = int(p.get("fps", 15))
    system = platform.system()
    if system == "Darwin":
        idx = int(p.get("display_id", 0))
        src = f"avfvideosrc capture-screen=true device-index={idx}"
    elif system == "Linux":
        src = "ximagesrc use-damage=0"
        if all(k in p for k in ("crop_x", "crop_y", "crop_w", "crop_h")):
            src += (f" startx={int(p['crop_x'])} starty={int(p['crop_y'])} "
                    f"endx={int(p['crop_x']) + int(p['crop_w']) - 1} "
                    f"endy={int(p['crop_y']) + int(p['crop_h']) - 1}")
    else:
        raise RuntimeError(f"Unsupported platform for screen capture: {system}")
    return (
        f"{src} ! videoconvert ! videoscale ! "
        f"video/x-raw,format=BGR,framerate={fps}/1 ! "
        f"appsink name=appsink sync=false max-buffers=2 drop=true"
    )


class ScreenCamera(Camera):
    """Capture the display as if it were a camera."""

    def __init__(self, spec: CameraSpec, frame_bus: Any) -> None:
        super().__init__(spec, frame_bus)
        self._pipeline: Any = None
        self._appsink: Any = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return
        import gi  # type: ignore
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # type: ignore

        if not Gst.is_initialized():
            Gst.init(None)
        pipeline_str = _build_pipeline(self.spec)
        log.info("screen %s pipeline: %s", self.id, pipeline_str)
        self._pipeline = Gst.parse_launch(pipeline_str)
        self._appsink = self._pipeline.get_by_name("appsink")
        self._pipeline.set_state(Gst.State.PLAYING)
        self._running = True
        self._task = asyncio.create_task(self._pull_loop(), name=f"screen/{self.id}")
        log.info("Screen camera %s started", self.id)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        if self._pipeline is not None:
            try:
                import gi  # type: ignore
                gi.require_version("Gst", "1.0")
                from gi.repository import Gst  # type: ignore
                self._pipeline.set_state(Gst.State.NULL)
            except Exception:  # pragma: no cover
                log.exception("error stopping screen pipeline")
            self._pipeline = None
            self._appsink = None
        log.info("Screen camera %s stopped", self.id)

    async def _pull_loop(self) -> None:
        import gi  # type: ignore
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # type: ignore

        try:
            while self._running:
                sample = await asyncio.to_thread(self._appsink.emit, "pull-sample")
                if sample is None:
                    continue
                buf = sample.get_buffer()
                s = sample.get_caps().get_structure(0)
                w, h = s.get_value("width"), s.get_value("height")
                ok, mi = buf.map(Gst.MapFlags.READ)
                if not ok:
                    continue
                try:
                    arr = np.frombuffer(mi.data, dtype=np.uint8).reshape(h, w, 3).copy()
                finally:
                    buf.unmap(mi)
                self.frame_bus.publish_nowait(self.id, Frame(
                    camera_id=self.id, timestamp_ns=time.time_ns(),
                    width=w, height=h, pixel_format=PixelFormat.BGR, data=arr,
                ))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("screen %s pull loop crashed", self.id)
