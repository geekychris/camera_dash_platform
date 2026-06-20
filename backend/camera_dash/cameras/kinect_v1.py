"""Kinect 360 (Kinect v1) driver — IR-structured-light depth + RGB.

The Kinect v1 is the original Xbox 360 sensor (Microsoft 1414/1473). It
exposes two USB endpoints — one for an RGB stream and one for the IR-derived
depth map — plus a tilt motor we leave alone.

We publish on TWO bus channels per capture:

* color channel — ``Frame`` (BGR, 640x480 @ 30 fps), suitable for the existing
  WebRTC/HLS preview path and any standard ``detector.*`` node.
* depth channel — ``DepthFrame`` (uint16 millimetres, 640x480 @ 30 fps). Zero
  values mean "no reading" (IR shadow, out-of-range, sensor noise) — depth
  nodes must treat zeros as invalid, not as zero-distance.

Requires:
    brew install libfreenect       # macOS
    apt install libfreenect-dev    # Linux
    pip install freenect           # Python wrapper (from libfreenect's
                                   # wrappers/python tree); on macOS you may
                                   # need to build it manually against the
                                   # brew-installed lib.

The wrapper isn't required at import time so the rest of the platform keeps
loading when libfreenect isn't installed. The driver raises a clear error if
``start`` is called without it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

import numpy as np

from ..pipeline.types import DepthFrame, Frame, PixelFormat
from .base import Camera, CameraSpec

log = logging.getLogger(__name__)

# Kinect v1 native streams are fixed at 640x480 @ 30 Hz. The library will
# happily return other resolutions but the depth/color alignment shipped from
# libfreenect's calibration only holds at the native size.
NATIVE_W = 640
NATIVE_H = 480
NATIVE_FPS = 30

# Approximate horizontal/vertical FOV from Microsoft's datasheet.
FOV_DEG = (57.0, 43.0)


def _check_freenect() -> Any:
    try:
        import freenect  # type: ignore
    except ImportError as exc:  # pragma: no cover - install-time check
        raise RuntimeError(
            "Kinect v1 driver requires the `freenect` Python wrapper. Install "
            "libfreenect (brew install libfreenect) and the Python binding "
            "from libfreenect's wrappers/python tree."
        ) from exc
    return freenect


class KinectV1Camera(Camera):
    """Captures aligned RGB + depth from a Kinect 360 via libfreenect.

    Capture runs in a worker thread (libfreenect uses libusb and blocks); each
    pair of frames is fanned out to both the color and depth channels of the
    shared ``FrameBus`` so existing nodes that consume ``source.camera`` see
    the BGR stream and new depth-aware nodes can subscribe to the depth one.
    """

    def __init__(self, spec: CameraSpec, frame_bus: Any) -> None:
        super().__init__(spec, frame_bus)
        self._task: asyncio.Task[None] | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        # Timestamp (monotonic seconds) of the most recently published frame.
        # The watchdog reads this from the main loop; the capture thread writes
        # it. A plain float assignment is atomic enough for our purposes.
        self._last_publish: float = 0.0
        # Pin native res into the spec so the streaming publisher caps + the
        # dashboard tile sizing agree with what we actually publish.
        spec.params.setdefault("width", NATIVE_W)
        spec.params.setdefault("height", NATIVE_H)
        spec.params.setdefault("fps", NATIVE_FPS)

    async def start(self) -> None:
        if self._running:
            return
        _check_freenect()  # fail fast with a clear error if missing
        self._stop.clear()
        self._last_publish = time.monotonic()
        self._running = True
        self._task = asyncio.create_task(self._capture_loop(), name=f"kinect_v1/{self.id}")
        self._watchdog_task = asyncio.create_task(self._watchdog(), name=f"kinect_v1/{self.id}/wd")
        log.info("Kinect v1 %s started", self.id)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop.set()
        for t_attr in ("_task", "_watchdog_task"):
            t = getattr(self, t_attr)
            if t is not None:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
                setattr(self, t_attr, None)
        log.info("Kinect v1 %s stopped", self.id)

    async def _watchdog(self) -> None:
        """Log when no depth/RGB frame has been published for too long.

        The sync_get_* libfreenect calls block until a complete frame lands,
        so when iso transfers are corrupted (marginal USB hub / cable / brick
        contact) the capture thread sits silent. The watchdog surfaces that
        condition without us having to introspect the blocked thread.
        """
        check_period = 5.0
        warn_after = 10.0
        warned = False
        try:
            while self._running and not self._stop.is_set():
                await asyncio.sleep(check_period)
                stale = time.monotonic() - self._last_publish
                if stale > warn_after and not warned:
                    log.warning(
                        "Kinect %s: no frames published in %.0fs. libfreenect "
                        "is likely stuck waiting for a clean iso packet. Most "
                        "common causes: marginal USB hub bandwidth, loose 12V "
                        "brick contact, or another USB device sharing the "
                        "upstream lane. Try unplugging the Kinect and replugging "
                        "into a different port on a powered USB 2.0 hub.",
                        self.id, stale)
                    warned = True
                elif stale <= warn_after and warned:
                    log.info("Kinect %s: frames flowing again", self.id)
                    warned = False
        except asyncio.CancelledError:
            raise

    async def _capture_loop(self) -> None:
        """Drive libfreenect in a worker thread; publish each pair to the bus."""
        try:
            await asyncio.to_thread(self._run_blocking)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Kinect v1 %s capture loop crashed", self.id)

    def _run_blocking(self) -> None:
        freenect = _check_freenect()
        device_index = int(self.spec.params.get("device_index", 0))
        # ``freenect.sync_get_*`` is a simpler API than the callback-driven one
        # and avoids us having to drive libfreenect's event loop ourselves. It
        # synchronously fetches the next available frame per call.
        period = 1.0 / NATIVE_FPS
        target_tilt = self.spec.params.get("tilt_deg")
        if isinstance(target_tilt, (int, float)):
            try:
                freenect.sync_set_tilt_degs(int(target_tilt), index=device_index)
            except Exception:  # pragma: no cover - motor not present on some clones
                log.warning("Kinect %s tilt failed; ignoring", self.id)

        open_warned = False  # rate-limit the "can't open device" logs
        while self._running and not self._stop.is_set():
            tick = time.monotonic()
            try:
                depth_pair = freenect.sync_get_depth(
                    index=device_index, format=freenect.DEPTH_REGISTERED,
                )
                rgb_pair = freenect.sync_get_video(
                    index=device_index, format=freenect.VIDEO_RGB,
                )
            except Exception:
                log.exception("Kinect %s frame fetch failed", self.id)
                time.sleep(0.5)
                continue
            if depth_pair is None or rgb_pair is None:
                # libfreenect prints "Can't open device" to stderr and returns
                # None when libusb can't claim the device — usually because
                # macOS's UVC kernel driver (or another process) already has
                # the RGB endpoint. Back off and retry instead of busy-looping.
                if not open_warned:
                    log.warning(
                        "Kinect %s: libfreenect could not open the device. Check "
                        "that the external 12V power brick is plugged in and that "
                        "no other process is holding the camera. On macOS, "
                        "unplug + replug the USB cable, then add the camera again. "
                        "Running as root also bypasses Apple's UVC claim.", self.id)
                    open_warned = True
                time.sleep(2.0)
                continue
            depth_arr, _depth_ts = depth_pair
            rgb_arr, _rgb_ts = rgb_pair
            open_warned = False

            ts_ns = time.time_ns()

            # libfreenect returns RGB; the rest of camera_dash speaks BGR.
            bgr = rgb_arr[:, :, ::-1].copy()
            frame = Frame(
                camera_id=self.id,
                timestamp_ns=ts_ns,
                width=NATIVE_W,
                height=NATIVE_H,
                pixel_format=PixelFormat.BGR,
                data=bgr,
            )
            self.frame_bus.publish_nowait(self.id, frame)

            # DEPTH_REGISTERED already returns uint16 mm aligned to the RGB
            # frame; libfreenect uses 0 for "no reading", which matches our
            # convention.
            depth = DepthFrame(
                camera_id=self.id,
                timestamp_ns=ts_ns,
                width=NATIVE_W,
                height=NATIVE_H,
                data=np.ascontiguousarray(depth_arr, dtype=np.uint16),
                fov_deg=FOV_DEG,
                metadata={"depth_ts": int(_depth_ts), "rgb_ts": int(_rgb_ts)},
            )
            self.frame_bus.publish_depth_nowait(self.id, depth)
            self._last_publish = time.monotonic()

            # Don't burn CPU if libfreenect feeds us frames faster than the
            # nominal rate (shouldn't happen, but cheap to guard against).
            elapsed = time.monotonic() - tick
            if elapsed < period:
                time.sleep(period - elapsed)

        with contextlib.suppress(Exception):
            freenect.sync_stop()

    def info(self) -> dict[str, Any]:
        out = super().info()
        # Expose to the frontend that this camera publishes a depth stream too.
        out["has_depth"] = True
        return out
