"""FLIR PureThermal + Lepton 3 / 3.5 driver.

Captures raw 16-bit thermal frames via GStreamer's ``avfvideosrc``/``v4l2src``
pinned to ``GRAY16_LE`` (PureThermal exposes the Lepton's 14-bit data in a
16-bit container). This avoids flirpy's OpenCV path which doesn't honor
``CAP_PROP_FOURCC=Y16`` on macOS AVFoundation.

Each :class:`Frame` carries both:

* ``data``      — a BGR uint8 colormapped image for display
* ``radiometric`` — the raw uint16 matrix (centi-Kelvin if the Lepton is in
                    radiometric / AGC-off mode; raw 14-bit thermal counts otherwise)

Calibration knobs (``spec.params``):

* ``radiometric_offset`` (default 0): added to each cell before Celsius conversion
* ``radiometric_scale``  (default 0.01): centi-Kelvin to Kelvin
* ``kelvin_offset``      (default 273.15): subtracted to yield Celsius

If your PureThermal isn't in radiometric mode, the temperature-on-hover values
will reflect raw AGC counts — use the GroupGets PureThermal Lepton UVC Capture
app (or flash the radiometric firmware) to switch modes.

This driver does NOT use ``flirpy`` for capture but keeps the package installed
since other utilities (calibration tools) may rely on it.
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
from ..utils.radiometric import colorize
from . import _libuvc
from .base import Camera, CameraSpec

log = logging.getLogger(__name__)


def _prefer_libuvc(spec: CameraSpec) -> bool:
    """Use libuvc on macOS so multiple Leptons can stream at once.

    Currently **opt-in only on macOS**. As of macOS 26 (Tahoe), ``uvc_open``
    segfaults inside libuvc's USB descriptor walk when opening a PureThermal,
    regardless of whether libuvc 0.0.7 or HEAD is installed and regardless
    of whether libusb is stable or HEAD. Confirmed via two consecutive
    crashes at the identical offset ``uvc_open+0x4bb4`` after upgrading both
    libraries to their development tips — the fault is below userspace,
    likely in libusb's descriptor read of the Tahoe USB stack. Until that
    lifts (libuvc/libusb ship a Tahoe-specific fix, or macOS leaves beta),
    we don't even try by default; the GStreamer/avfvideosrc path keeps
    single-FLIR working as before.

    To opt in (e.g. once macOS gets fixed and you want to re-test):
      * ``CAMERA_DASH_FLIR_BACKEND=libuvc`` env var, or
      * ``spec.params['backend'] == 'libuvc'`` for a specific camera.

    Prerequisites for the opt-in path:
      * Running as root (kernel UVC claim by VDCAssistant)
      * libuvc + libusb installed (``brew install libuvc``)

    Linux always uses GStreamer/v4l2 — libuvc would also work there but
    v4l2 supports multi-device without privilege escalation, so there's no
    reason to deviate from the well-trodden path.
    """
    if platform.system() != "Darwin":
        return False
    if spec.params.get("backend") == "gstreamer":
        return False
    import os
    backend_env = os.environ.get("CAMERA_DASH_FLIR_BACKEND", "").lower()
    if backend_env == "gstreamer":
        return False
    # Default: do NOT attempt libuvc on macOS — see docstring.
    if spec.params.get("backend") != "libuvc" and backend_env != "libuvc":
        return False
    if os.geteuid() != 0:
        log.warning("FLIR libuvc backend requested but process is not root; falling back to GStreamer")
        return False
    return _libuvc.available()


def _source_element(params: dict[str, Any]) -> str:
    # Default device-name matches what macOS reports for PureThermal so the
    # FLIR is found regardless of USB plug order. Override with ``device_name``
    # or ``device_index`` in CameraSpec.params if your device shows differently.
    name = params.get("device_name", "PureThermal (fw:v1.0.0)")
    system = platform.system()
    if system == "Darwin":
        from .uvc import _resolve_index
        idx = _resolve_index({"device_name": name, **params}, default=0)
        return f"avfvideosrc device-index={idx}"
    if system == "Linux":
        dev = params.get("device", f"/dev/video{int(params.get('device_index', 0))}")
        return f"v4l2src device={dev}"
    raise RuntimeError(f"Unsupported platform: {system}")


def _build_pipeline(spec: CameraSpec) -> str:
    src = _source_element(spec.params)
    w = int(spec.params.get("width", 160))
    h = int(spec.params.get("height", 120))
    fps = int(spec.params.get("fps", 9))
    return (
        f"{src} ! videoconvert ! "
        f"video/x-raw,format=GRAY16_LE,width={w},height={h},framerate={fps}/1 ! "
        f"appsink name=appsink emit-signals=true sync=false max-buffers=2 drop=true"
    )


class FlirLeptonCamera(Camera):
    """Captures thermal frames from a PureThermal-attached Lepton via GStreamer."""

    def __init__(self, spec: CameraSpec, frame_bus: Any) -> None:
        super().__init__(spec, frame_bus)
        self._pipeline: Any = None
        self._appsink: Any = None
        self._task: asyncio.Task[None] | None = None
        # libuvc-mode state (set when start() picks the libuvc backend)
        self._uvc_ctx: Any = None
        self._uvc_handle: Any = None
        self._uvc_stream: Any = None
        self._uvc_stop = asyncio.Event()
        # Pin the Lepton's native dimensions into the spec so the streaming
        # publisher gets the right appsrc caps (160x120 BGR @ 9fps) instead of
        # the catch-all 1280x720x30 default. Without this, x264enc rejects the
        # downscaled-from-160x120 buffers and no MediaMTX path comes up.
        spec.params.setdefault("width", 160)
        spec.params.setdefault("height", 120)
        spec.params.setdefault("fps", 9)

    async def start(self) -> None:
        if self._running:
            return
        if _prefer_libuvc(self.spec):
            try:
                await self._start_libuvc()
            except PermissionError as exc:
                # macOS VDCAssistant has the kernel UVC claim. libuvc only
                # gets the interface with root or a kext exclusion. Fall back
                # to GStreamer so single-FLIR setups keep working — multi-
                # FLIR still requires root, but we log the path forward.
                log.warning(
                    "FLIR %s: libuvc denied access (%s). Falling back to "
                    "GStreamer/avfvideosrc — multi-FLIR concurrency requires "
                    "running the backend as root (or installing a kext "
                    "exclusion for VID 0x1E4E). To skip the libuvc attempt "
                    "next time, set CAMERA_DASH_FLIR_BACKEND=gstreamer.",
                    self.id, exc)
                self._start_gstreamer()
                self._running = True
                self._task = asyncio.create_task(self._pull_loop(), name=f"flir/{self.id}")
            except Exception:
                log.exception("FLIR %s: libuvc start failed; falling back to GStreamer", self.id)
                self._start_gstreamer()
                self._running = True
                self._task = asyncio.create_task(self._pull_loop(), name=f"flir/{self.id}")
        else:
            self._start_gstreamer()
            self._running = True
            self._task = asyncio.create_task(self._pull_loop(), name=f"flir/{self.id}")
        log.info("FLIR Lepton %s started", self.id)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._uvc_stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        if self._uvc_stream is not None:
            with contextlib.suppress(Exception):
                _libuvc.close_stream(self._uvc_stream)
            self._uvc_stream = None
        if self._uvc_handle is not None:
            with contextlib.suppress(Exception):
                _libuvc.close_device(self._uvc_handle)
            self._uvc_handle = None
        if self._uvc_ctx is not None:
            with contextlib.suppress(Exception):
                _libuvc.exit_(self._uvc_ctx)
            self._uvc_ctx = None
        if self._pipeline is not None:
            try:
                import gi  # type: ignore
                gi.require_version("Gst", "1.0")
                from gi.repository import Gst  # type: ignore
                self._pipeline.set_state(Gst.State.NULL)
            except Exception:  # pragma: no cover
                log.exception("error stopping FLIR pipeline")
            self._pipeline = None
            self._appsink = None
        log.info("FLIR Lepton %s stopped", self.id)

    async def _start_libuvc(self) -> None:
        """Open one specific Lepton via libuvc, sidestepping AVFoundation.

        The user's ``device_index`` is interpreted as an index into the
        PureThermal devices sorted by (bus, address) — stable across calls
        within an OS session. So three Leptons enumerate as 0, 1, 2 in a
        consistent order regardless of plug timing.
        """
        device_index = int(self.spec.params.get("device_index", 0))
        width = int(self.spec.params.get("width", 160))
        height = int(self.spec.params.get("height", 120))
        fps = int(self.spec.params.get("fps", 9))
        # Bring up libuvc + pick a device on a worker thread (uvc_open syscalls).
        ctx, handle, stream = await asyncio.to_thread(
            self._libuvc_open_device, device_index, width, height, fps,
        )
        self._uvc_ctx = ctx
        self._uvc_handle = handle
        self._uvc_stream = stream
        self._uvc_stop.clear()
        self._running = True
        self._task = asyncio.create_task(self._uvc_pull_loop(), name=f"flir/{self.id}/uvc")

    def _libuvc_open_device(self, device_index: int, width: int, height: int, fps: int):
        ctx = _libuvc.init()
        entries = _libuvc.list_purethermal(ctx)
        if not entries:
            _libuvc.exit_(ctx)
            raise RuntimeError(
                "libuvc: no PureThermal devices found on USB. Is the camera plugged in?")
        if device_index < 0 or device_index >= len(entries):
            _libuvc.exit_(ctx)
            raise RuntimeError(
                f"libuvc: device_index={device_index} out of range "
                f"(found {len(entries)} PureThermal device{'s' if len(entries) != 1 else ''})")
        entry = entries[device_index]
        log.info("FLIR %s opening libuvc device idx=%d bus=%d addr=%d serial=%r",
                 self.id, device_index, entry.bus, entry.address, entry.serial)
        handle = None
        stream = None
        try:
            handle = _libuvc.open_by_address(ctx, entry.bus, entry.address)
            stream = _libuvc.open_stream(handle, width, height, fps)
            return ctx, handle, stream
        except Exception:
            if stream is not None:
                with contextlib.suppress(Exception):
                    _libuvc.close_stream(stream)
            if handle is not None:
                with contextlib.suppress(Exception):
                    _libuvc.close_device(handle)
            _libuvc.exit_(ctx)
            raise

    async def _uvc_pull_loop(self) -> None:
        """Pull Y16 frames from libuvc in a worker thread; publish to the bus."""
        try:
            while self._running and not self._uvc_stop.is_set():
                radio = await asyncio.to_thread(
                    _libuvc.stream_get_frame, self._uvc_stream, 200_000,
                )
                if radio is None:
                    continue
                h, w = radio.shape
                bgr = colorize(radio)
                frame = Frame(
                    camera_id=self.id,
                    timestamp_ns=time.time_ns(),
                    width=w,
                    height=h,
                    pixel_format=PixelFormat.THERMAL14,
                    data=bgr,
                    radiometric=radio,
                    metadata={
                        "colormap": "inferno",
                        "radio_min": int(radio.min()),
                        "radio_max": int(radio.max()),
                        "backend": "libuvc",
                    },
                )
                self.frame_bus.publish_nowait(self.id, frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("FLIR %s libuvc pull loop crashed", self.id)

    def _start_gstreamer(self) -> None:
        import gi  # type: ignore
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # type: ignore

        if not Gst.is_initialized():
            Gst.init(None)

        pipeline_str = _build_pipeline(self.spec)
        log.info("FLIR %s pipeline: %s", self.id, pipeline_str)
        self._pipeline = Gst.parse_launch(pipeline_str)
        self._appsink = self._pipeline.get_by_name("appsink")
        ret = self._pipeline.set_state(Gst.State.PLAYING)
        # macOS AVFoundation negotiates UVC claims one at a time. If we kick
        # off the next FLIR's pipeline before this one has reached PLAYING,
        # AVFoundation drops the second open silently and that camera never
        # produces frames. Wait until the pipeline either confirms PLAYING or
        # the timeout fires so the manager's sequential start is actually
        # sequential at the kernel level.
        if ret == Gst.StateChangeReturn.ASYNC:
            state_ret, state, _pending = self._pipeline.get_state(5 * Gst.SECOND)
            if state != Gst.State.PLAYING:
                log.warning("FLIR %s did not reach PLAYING within 5s (ret=%s, state=%s)",
                            self.id, state_ret, state)
            else:
                log.info("FLIR %s pipeline PLAYING", self.id)

    async def _pull_loop(self) -> None:
        """Synchronous pull-sample in a worker thread — more reliable than the
        new-sample signal which doesn't fire on macOS GStreamer in some setups.
        """
        import gi  # type: ignore
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # type: ignore

        try:
            while self._running:
                sample = await asyncio.to_thread(self._appsink.emit, "pull-sample")
                if sample is None:
                    continue
                buf = sample.get_buffer()
                caps = sample.get_caps().get_structure(0)
                w = caps.get_value("width")
                h = caps.get_value("height")
                ok, mi = buf.map(Gst.MapFlags.READ)
                if not ok:
                    continue
                try:
                    radio = np.frombuffer(mi.data, dtype=np.uint16).reshape(h, w).copy()
                finally:
                    buf.unmap(mi)

                bgr = colorize(radio)
                frame = Frame(
                    camera_id=self.id,
                    timestamp_ns=time.time_ns(),
                    width=w,
                    height=h,
                    pixel_format=PixelFormat.THERMAL14,
                    data=bgr,
                    radiometric=radio,
                    metadata={
                        "colormap": "inferno",
                        "radio_min": int(radio.min()),
                        "radio_max": int(radio.max()),
                    },
                )
                self.frame_bus.publish_nowait(self.id, frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("FLIR %s pull loop crashed", self.id)
