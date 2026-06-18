"""Per-camera GStreamer publisher.

Subscribes to a camera's frames on the :class:`FrameBus` and pushes them into a
GStreamer pipeline that encodes (H.264) and ships the stream to MediaMTX via
``rtspclientsink``. MediaMTX then exposes the same stream as WebRTC / HLS / RTSP
for the browser.

Decoupling capture from streaming this way lets us:
* turn streaming on/off without restarting capture
* run multiple subscribers (pipeline + stream + radiometric WS) off one capture
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from ..pipeline.types import Frame
from .frame_bus import FrameBus

log = logging.getLogger(__name__)


def build_publisher_pipeline(camera_id: str, width: int, height: int, fps: int,
                              rtsp_url: str) -> str:
    """Encoder pipeline: appsrc -> H.264 -> RTSP push to MediaMTX."""
    return (
        f"appsrc name=src is-live=true format=time do-timestamp=true "
        f"caps=video/x-raw,format=BGR,width={width},height={height},framerate={fps}/1 ! "
        f"videoconvert ! video/x-raw,format=I420 ! "
        f"x264enc tune=zerolatency speed-preset=ultrafast bitrate=2000 key-int-max={fps*2} ! "
        f"h264parse config-interval=-1 ! "
        f"rtspclientsink location={rtsp_url} protocols=tcp"
    )


class StreamPublisher:
    """Encodes one camera and pushes RTSP to MediaMTX."""

    def __init__(self, camera_id: str, frame_bus: FrameBus, rtsp_url: str,
                 width: int = 1280, height: int = 720, fps: int = 30) -> None:
        self.camera_id = camera_id
        self.frame_bus = frame_bus
        self.rtsp_url = rtsp_url
        self.width = width
        self.height = height
        self.fps = fps
        self._pipeline: Any = None
        self._appsrc: Any = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        import gi  # type: ignore
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # type: ignore

        if not Gst.is_initialized():
            Gst.init(None)
        pipeline_str = build_publisher_pipeline(
            self.camera_id, self.width, self.height, self.fps, self.rtsp_url)
        log.info("stream %s pipeline: %s", self.camera_id, pipeline_str)
        self._pipeline = Gst.parse_launch(pipeline_str)
        self._appsrc = self._pipeline.get_by_name("src")
        self._pipeline.set_state(Gst.State.PLAYING)
        self._running = True
        self._task = asyncio.create_task(self._pump(), name=f"stream/{self.camera_id}")

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
                pass
            self._pipeline = None
        log.info("stream %s stopped", self.camera_id)

    async def _pump(self) -> None:
        import gi  # type: ignore
        gi.require_version("Gst", "1.0")
        from gi.repository import GLib, Gst  # type: ignore

        q = await self.frame_bus.subscribe(self.camera_id, depth=2)
        start_ts = time.monotonic()
        try:
            while self._running:
                frame: Frame = await q.get()
                buf = Gst.Buffer.new_wrapped(bytes(frame.data))
                pts_ns = int((time.monotonic() - start_ts) * GLib.USEC_PER_SEC * 1000)
                buf.pts = pts_ns
                buf.duration = int(1e9 / self.fps)
                self._appsrc.emit("push-buffer", buf)
        finally:
            await self.frame_bus.unsubscribe(self.camera_id, q)


class StreamingManager:
    """Owns one :class:`StreamPublisher` per started camera."""

    def __init__(self, settings: Any, frame_bus: FrameBus) -> None:
        self.settings = settings
        self.frame_bus = frame_bus
        self._publishers: dict[str, StreamPublisher] = {}

    def url_for(self, camera_id: str) -> str:
        s = self.settings.streaming
        return f"rtsp://{s.mediamtx_host}:{s.mediamtx_rtsp_port}/camera/{camera_id}"

    async def attach(self, camera_id: str, width: int, height: int, fps: int) -> None:
        if camera_id in self._publishers:
            return
        pub = StreamPublisher(
            camera_id=camera_id,
            frame_bus=self.frame_bus,
            rtsp_url=self.url_for(camera_id),
            width=width, height=height, fps=fps,
        )
        try:
            await pub.start()
        except Exception:
            log.exception("failed to attach stream publisher for %s", camera_id)
            return
        self._publishers[camera_id] = pub

    async def detach(self, camera_id: str) -> None:
        pub = self._publishers.pop(camera_id, None)
        if pub:
            await pub.stop()

    async def stop_all(self) -> None:
        await asyncio.gather(*(p.stop() for p in self._publishers.values()),
                             return_exceptions=True)
        self._publishers.clear()
