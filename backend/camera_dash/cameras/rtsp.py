"""RTSP / IP camera driver via GStreamer.

Works with any RTSP-publishing camera (HikVision, Reolink, Amcrest, ONVIF) and
also generic ``rtsp://`` URLs (e.g. another MediaMTX path).

Spec params:
    url             rtsp://user:pass@host:port/stream   (required)
    width/height    re-scale target (optional; if omitted, native)
    fps             target frames/sec (optional)
    transport       "tcp" (default, more reliable) or "udp"
    latency_ms      jitter buffer; lower = lower latency, higher = smoother (default 200)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np

from ..pipeline.types import Frame, PixelFormat
from .base import Camera, CameraSpec

log = logging.getLogger(__name__)


def _build_pipeline(spec: CameraSpec) -> str:
    p = spec.params
    url = p.get("url")
    if not url:
        raise ValueError(f"RTSP camera {spec.id}: params.url is required")
    transport = p.get("transport", "tcp")
    latency = int(p.get("latency_ms", 200))
    caps = "video/x-raw,format=BGR"
    if "width" in p and "height" in p:
        caps += f",width={int(p['width'])},height={int(p['height'])}"
    if "fps" in p:
        caps += f",framerate={int(p['fps'])}/1"
    return (
        f"rtspsrc location={url} protocols={transport} latency={latency} ! "
        f"rtpjitterbuffer ! decodebin ! videoconvert ! videoscale ! {caps} ! "
        f"appsink name=appsink sync=false max-buffers=2 drop=true"
    )


class RtspCamera(Camera):
    """RTSP / IP camera capture via GStreamer."""

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
        log.info("rtsp %s pipeline: %s", self.id, pipeline_str)
        self._pipeline = Gst.parse_launch(pipeline_str)
        self._appsink = self._pipeline.get_by_name("appsink")
        self._pipeline.set_state(Gst.State.PLAYING)
        self._running = True
        self._task = asyncio.create_task(self._pull_loop(), name=f"rtsp/{self.id}")
        log.info("RTSP camera %s started", self.id)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            import contextlib
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
                log.exception("error stopping RTSP pipeline")
            self._pipeline = None
            self._appsink = None
        log.info("RTSP camera %s stopped", self.id)

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
            log.exception("RTSP %s pull loop crashed", self.id)
