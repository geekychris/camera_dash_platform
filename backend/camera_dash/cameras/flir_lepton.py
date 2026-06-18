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
import logging
import platform
import time
from typing import Any

import numpy as np

from ..pipeline.types import Frame, PixelFormat
from ..utils.radiometric import colorize
from .base import Camera, CameraSpec

log = logging.getLogger(__name__)


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

    async def start(self) -> None:
        if self._running:
            return
        self._start_gstreamer()
        self._running = True
        self._task = asyncio.create_task(self._pull_loop(), name=f"flir/{self.id}")
        log.info("FLIR Lepton %s started", self.id)

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
                log.exception("error stopping FLIR pipeline")
            self._pipeline = None
            self._appsink = None
        log.info("FLIR Lepton %s stopped", self.id)

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
        self._pipeline.set_state(Gst.State.PLAYING)

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
