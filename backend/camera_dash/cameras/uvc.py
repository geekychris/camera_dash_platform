"""USB UVC camera driver via GStreamer.

Builds a per-camera pipeline of the shape::

    <src> ! videoconvert ! video/x-raw,format=BGR ! tee name=t \\
        t. ! queue ! appsink   (frames -> FrameBus)
        t. ! queue ! x264enc ! h264parse ! rtspclientsink ...   (added by streaming.gst)

For the camera itself we only own the appsink branch — the encoder branch is
attached by :mod:`camera_dash.streaming.gst` when streaming is enabled.
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


def _source_element(params: dict[str, Any]) -> str:
    """Return the GStreamer source element string for this platform.

    Prefers ``device_name`` (matched against GStreamer's DeviceMonitor) over
    ``device_index`` because USB device-index isn't stable across replugs.
    """
    system = platform.system()
    if system == "Darwin":
        idx = _resolve_index(params, default=0)
        return f"avfvideosrc device-index={idx}"
    if system == "Linux":
        dev = params.get("device") or _resolve_v4l2(params)
        return f"v4l2src device={dev}"
    raise RuntimeError(f"Unsupported platform: {system}")


def _resolve_index(params: dict[str, Any], default: int) -> int:
    """Pick a device index for the source element.

    Resolution order:
      1. ``device_index`` if explicitly set in ``params`` — wins over name
         lookup so users with multiple identical devices (e.g. three
         PureThermal/Leptons) can pin a specific one. ``device_index = 0``
         counts as explicit only when the key is present in ``params``.
      2. ``device_name`` looked up via GStreamer DeviceMonitor.
      3. ``default`` (typically 0).
    """
    # Explicit index wins. Avoid the name lookup entirely — otherwise the
    # first device matching the name pattern silently shadows the user's pick.
    if "device_index" in params and params["device_index"] is not None:
        try:
            return int(params["device_index"])
        except (TypeError, ValueError):
            pass
    name = params.get("device_name")
    if not name:
        return int(params.get("device_index", default))
    try:
        import gi  # type: ignore
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # type: ignore
        if not Gst.is_initialized():
            Gst.init(None)
        monitor = Gst.DeviceMonitor.new()
        monitor.add_filter("Video/Source", None)
        monitor.start()
        for i, d in enumerate(monitor.get_devices() or []):
            if d.get_display_name() == name:
                monitor.stop()
                return i
        monitor.stop()
    except Exception:  # pragma: no cover
        log.exception("device-name lookup failed")
    log.warning("camera device-name %r not found; falling back to device_index", name)
    return int(params.get("device_index", default))


def _resolve_v4l2(params: dict[str, Any]) -> str:
    # Prefer an explicit device path — discover sets this from GStreamer's
    # device.path so the user picks the actual /dev/videoN, not a sequence
    # index that doesn't match. Fall back to device_index for back-compat
    # with pre-discover-path saved camera specs.
    dev = params.get("device")
    if isinstance(dev, str) and dev:
        return dev
    return f"/dev/video{int(params.get('device_index', 0))}"


def build_appsink_pipeline(spec: CameraSpec) -> str:
    src = _source_element(spec.params)
    w = int(spec.params.get("width", 1280))
    h = int(spec.params.get("height", 720))
    fps = int(spec.params.get("fps", 30))
    return (
        f"{src} ! videoconvert ! videoscale ! "
        f"video/x-raw,format=BGR,width={w},height={h},framerate={fps}/1 ! "
        f"appsink name=appsink emit-signals=true sync=false max-buffers=2 drop=true"
    )


class UvcCamera(Camera):
    """USB UVC capture. Uses GStreamer; degrades to OpenCV VideoCapture as fallback."""

    def __init__(self, spec: CameraSpec, frame_bus: Any) -> None:
        super().__init__(spec, frame_bus)
        self._pipeline: Any = None  # Gst.Pipeline
        self._appsink: Any = None
        self._task: asyncio.Task[None] | None = None
        self._fallback_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return
        try:
            self._start_gstreamer()
            self._running = True
            self._task = asyncio.create_task(self._pull_loop(), name=f"uvc/{self.id}")
        except Exception as exc:  # pragma: no cover - depends on host
            log.warning("GStreamer unavailable (%s); falling back to OpenCV VideoCapture", exc)
            self._running = True
            self._start_opencv_fallback()
        log.info("camera %s started", self.id)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for t in (self._task, self._fallback_task):
            if t is not None:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
        self._task = None
        self._fallback_task = None
        if self._pipeline is not None:
            try:
                import gi  # type: ignore
                gi.require_version("Gst", "1.0")
                from gi.repository import Gst  # type: ignore
                self._pipeline.set_state(Gst.State.NULL)
            except Exception:  # pragma: no cover
                pass
            self._pipeline = None
            self._appsink = None
        log.info("camera %s stopped", self.id)

    # ----- GStreamer path -----

    def _start_gstreamer(self) -> None:
        import gi  # type: ignore
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # type: ignore

        if not Gst.is_initialized():
            Gst.init(None)

        pipeline_str = build_appsink_pipeline(self.spec)
        log.info("camera %s pipeline: %s", self.id, pipeline_str)
        self._pipeline = Gst.parse_launch(pipeline_str)
        self._appsink = self._pipeline.get_by_name("appsink")
        self._pipeline.set_state(Gst.State.PLAYING)

    async def _pull_loop(self) -> None:
        """Sync pull-sample in a worker thread (signal callbacks unreliable on macOS)."""
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
                w = s.get_value("width")
                h = s.get_value("height")
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
            log.exception("UVC %s pull loop crashed", self.id)

    # ----- OpenCV fallback (used when GStreamer isn't available) -----

    def _start_opencv_fallback(self) -> None:
        import cv2

        idx = int(self.spec.params.get("device_index", 0))
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            raise RuntimeError(f"could not open camera index {idx}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.spec.params.get("width", 1280)))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.spec.params.get("height", 720)))
        cap.set(cv2.CAP_PROP_FPS, int(self.spec.params.get("fps", 30)))

        async def _loop() -> None:
            try:
                while self._running:
                    ok, frame_bgr = await asyncio.to_thread(cap.read)
                    if not ok:
                        await asyncio.sleep(0.05)
                        continue
                    h, w = frame_bgr.shape[:2]
                    frame = Frame(
                        camera_id=self.id,
                        timestamp_ns=time.time_ns(),
                        width=w,
                        height=h,
                        pixel_format=PixelFormat.BGR,
                        data=frame_bgr,
                    )
                    self.frame_bus.publish_nowait(self.id, frame)
            finally:
                cap.release()

        self._fallback_task = asyncio.create_task(_loop(), name=f"uvc-fallback/{self.id}")


def list_devices() -> list[dict[str, Any]]:
    """Best-effort enumeration of UVC cameras visible to GStreamer.

    Returns a list of ``{index, name, caps, device}`` dicts, where ``device``
    is the v4l2 path (``/dev/videoN``) on Linux when GStreamer exposes it.
    Filters out non-streaming nodes (UVC metadata interfaces, Pi ISP
    backend stages) by checking for at least one usable pixel format in
    the device's caps — a node that ``v4l2-ctl --list-formats`` reports as
    empty shows up here as an empty caps string and gets dropped.
    Caller (Camera Manager UI / discover endpoint) prefers ``device`` over
    ``index`` on Linux since the index→/dev/videoN mapping is not stable.
    """
    devices: list[dict[str, Any]] = []
    try:
        import gi  # type: ignore
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # type: ignore

        if not Gst.is_initialized():
            Gst.init(None)
        monitor = Gst.DeviceMonitor.new()
        monitor.add_filter("Video/Source", None)
        monitor.start()
        for i, dev in enumerate(monitor.get_devices() or []):
            caps_obj = dev.get_caps()
            caps_str = caps_obj.to_string() if caps_obj else ""
            # Pi ISP backend stages (`pispbe`) advertise Video/Source caps
            # but aren't user-facing cameras. Drop them.
            name = dev.get_display_name() or ""
            if name.lower().startswith("pispbe") or name == "pispbe":
                continue
            # On Linux a UVC camera typically exposes two /dev/video<N>:
            # one with real formats, one for metadata only. The metadata
            # node has empty caps — skip it.
            if not caps_str or caps_str == "EMPTY":
                continue
            entry: dict[str, Any] = {
                "index": i,
                "name": dev.get_display_name(),
                "caps": caps_str[:200],
            }
            # Extract the v4l2 device path (e.g. /dev/video0) when present.
            # GstV4l2Device exposes it via the GstStructure properties on Linux;
            # macOS avfvideosrc devices don't have an analogous stable path so
            # the field is absent there.
            try:
                props = dev.get_properties()
                if props is not None:
                    path = props.get_string("device.path")
                    if path:
                        entry["device"] = path
            except Exception:  # pragma: no cover
                pass
            devices.append(entry)
        monitor.stop()
    except Exception:  # pragma: no cover
        log.exception("GStreamer device enumeration failed")
    return devices
