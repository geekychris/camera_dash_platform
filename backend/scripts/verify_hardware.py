"""Post-install hardware sanity check.

Opens the built-in MacBook camera (UVC index 0) and the FLIR Lepton
(PureThermal) one after the other, grabs a frame from each, prints shape +
basic stats. Doesn't need the backend running.
"""

from __future__ import annotations

import sys


def check_uvc(index: int = 0) -> None:
    print(f"\n--- UVC index {index} (laptop camera) ---")
    import cv2

    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        print(f"  FAIL: could not open VideoCapture({index})")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    ok, frame = cap.read()
    if not ok:
        print("  FAIL: read returned False")
        cap.release()
        return
    print(f"  OK: shape={frame.shape}, dtype={frame.dtype}, mean={frame.mean():.1f}")
    cap.release()


def check_gstreamer() -> None:
    print("\n--- GStreamer Python bindings ---")
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        print(f"  OK: Gst version {Gst.version_string()}")
        monitor = Gst.DeviceMonitor.new()
        monitor.add_filter("Video/Source", None)
        monitor.start()
        devs = monitor.get_devices() or []
        print(f"  {len(devs)} video source(s) seen by GStreamer:")
        for i, d in enumerate(devs):
            print(f"    [{i}] {d.get_display_name()}")
        monitor.stop()
    except Exception as exc:
        print(f"  FAIL: {exc}")


def check_flir() -> None:
    print("\n--- FLIR Lepton (flirpy) ---")
    try:
        from flirpy.camera.lepton import Lepton
    except ImportError as exc:
        print(f"  SKIP: flirpy not installed ({exc})")
        return
    try:
        cam = Lepton()
        cam.setup_video()
        frame = cam.grab()
        if frame is None:
            print("  FAIL: grab returned None")
        else:
            t_min = (frame.min() / 100.0) - 273.15
            t_max = (frame.max() / 100.0) - 273.15
            t_mean = (frame.mean() / 100.0) - 273.15
            print(f"  OK: shape={frame.shape}, dtype={frame.dtype}")
            print(f"  temperature range: {t_min:.1f}C .. {t_max:.1f}C (mean {t_mean:.1f}C)")
        cam.close()
    except Exception as exc:
        print(f"  FAIL: {exc}")


def main() -> int:
    check_uvc(0)
    check_gstreamer()
    check_flir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
