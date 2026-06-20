"""Enable Lepton radiometric (TLinear) mode via libuvc XU controls.

The PureThermal carrier exposes Lepton CCI commands as UVC Extension Unit
controls. To get real temperature in the Y16 stream we need:
  - AGC OFF        (unit 3 / selector 1)   value 0
  - TLinear ON     (unit 5 / selector 49)  value 1
  - TLinear 0.01 K (unit 5 / selector 50)  value 1  (0 = 0.1 K low-res)

On macOS the device must NOT be open by any other process, AND the script
must run as root — otherwise Apple's VDCAssistant has the kernel UVC driver
claim and libuvc cannot open the interface (UVC_ERROR_ACCESS = -3).

Requires libuvc (brew install libuvc).
"""

from __future__ import annotations

import ctypes.util
import os
import sys
from ctypes import CDLL, POINTER, Structure, byref, c_int, c_uint8, c_uint32, c_void_p

PT_USB_VID = 0x1E4E
PT_USB_PID = 0x0100

AGC_UNIT_ID = 3
RAD_UNIT_ID = 5
AGC_ENABLE_STATE = 1
RAD_TLINEAR_ENABLE_STATE = 49
RAD_TLINEAR_RESOLUTION = 50
UVC_GET_CUR = 0x81


def _load_libuvc() -> CDLL:
    path = ctypes.util.find_library("uvc")
    if not path:
        for cand in ("/opt/homebrew/lib/libuvc.dylib", "/usr/local/lib/libuvc.dylib",
                     "/usr/lib/libuvc.so.0", "/usr/lib/x86_64-linux-gnu/libuvc.so.0"):
            if os.path.exists(cand):
                path = cand
                break
    if not path:
        sys.exit("libuvc not found — `brew install libuvc` (macOS) or `apt install libuvc-dev` (Linux)")
    print(f"libuvc: {path}")
    return CDLL(path)


lib = _load_libuvc()


class uvc_context(Structure): pass
class uvc_device(Structure): pass
class uvc_device_handle(Structure): pass


lib.uvc_init.argtypes = [POINTER(POINTER(uvc_context)), c_void_p]
lib.uvc_init.restype = c_int
lib.uvc_find_device.argtypes = [
    POINTER(uvc_context), POINTER(POINTER(uvc_device)), c_int, c_int, c_void_p,
]
lib.uvc_find_device.restype = c_int
lib.uvc_open.argtypes = [POINTER(uvc_device), POINTER(POINTER(uvc_device_handle))]
lib.uvc_open.restype = c_int
lib.uvc_close.argtypes = [POINTER(uvc_device_handle)]
lib.uvc_close.restype = None
lib.uvc_unref_device.argtypes = [POINTER(uvc_device)]
lib.uvc_unref_device.restype = None
lib.uvc_exit.argtypes = [POINTER(uvc_context)]
lib.uvc_exit.restype = None
lib.uvc_set_ctrl.argtypes = [POINTER(uvc_device_handle), c_uint8, c_uint8, c_void_p, c_int]
lib.uvc_set_ctrl.restype = c_int
lib.uvc_get_ctrl.argtypes = [
    POINTER(uvc_device_handle), c_uint8, c_uint8, c_void_p, c_int, c_int,
]
lib.uvc_get_ctrl.restype = c_int


def set_u32(devh, unit: int, sel: int, value: int) -> int:
    buf = c_uint32(value)
    return lib.uvc_set_ctrl(devh, unit, sel, byref(buf), 4)


def get_u32(devh, unit: int, sel: int) -> tuple[int, int]:
    buf = c_uint32(0)
    r = lib.uvc_get_ctrl(devh, unit, sel, byref(buf), 4, UVC_GET_CUR)
    return r, buf.value


def main() -> int:
    ctx = POINTER(uvc_context)()
    dev = POINTER(uvc_device)()
    devh = POINTER(uvc_device_handle)()

    r = lib.uvc_init(byref(ctx), None)
    if r < 0:
        print(f"uvc_init failed: {r}", file=sys.stderr)
        return 1
    try:
        r = lib.uvc_find_device(ctx, byref(dev), PT_USB_VID, PT_USB_PID, None)
        if r < 0:
            print(f"uvc_find_device failed: {r} — PureThermal not plugged in?", file=sys.stderr)
            return 1
        try:
            r = lib.uvc_open(dev, byref(devh))
            if r < 0:
                print(
                    f"uvc_open failed: {r}\n"
                    "  -3 = UVC_ERROR_ACCESS (most common on macOS):\n"
                    "       another process has the device open OR you need root.\n"
                    "       Stop camera_dash's FLIR first (DELETE /api/cameras/flir)\n"
                    "       and re-run this script with sudo.",
                    file=sys.stderr,
                )
                return 1
            try:
                rc1, agc = get_u32(devh, AGC_UNIT_ID, AGC_ENABLE_STATE)
                rc2, tlin = get_u32(devh, RAD_UNIT_ID, RAD_TLINEAR_ENABLE_STATE)
                rc3, res = get_u32(devh, RAD_UNIT_ID, RAD_TLINEAR_RESOLUTION)
                print(
                    f"before:  AGC={agc if rc1 == 0 else f'err {rc1}'}  "
                    f"TLinear={tlin if rc2 == 0 else f'err {rc2}'}  "
                    f"Resolution={res if rc3 == 0 else f'err {rc3}'}"
                )

                r1 = set_u32(devh, AGC_UNIT_ID, AGC_ENABLE_STATE, 0)
                r2 = set_u32(devh, RAD_UNIT_ID, RAD_TLINEAR_ENABLE_STATE, 1)
                r3 = set_u32(devh, RAD_UNIT_ID, RAD_TLINEAR_RESOLUTION, 1)
                print(f"set rc:  AGC=>0:{r1}  TLinear=>1:{r2}  Resolution=>1(0.01K):{r3}")

                _, agc2 = get_u32(devh, AGC_UNIT_ID, AGC_ENABLE_STATE)
                _, tlin2 = get_u32(devh, RAD_UNIT_ID, RAD_TLINEAR_ENABLE_STATE)
                _, res2 = get_u32(devh, RAD_UNIT_ID, RAD_TLINEAR_RESOLUTION)
                print(f"after:   AGC={agc2}  TLinear={tlin2}  Resolution={res2}")

                ok = agc2 == 0 and tlin2 == 1 and res2 == 1
                print("RADIOMETRIC MODE ENABLED ✓" if ok else "verification mismatch — see above")
                return 0 if ok else 2
            finally:
                lib.uvc_close(devh)
        finally:
            lib.uvc_unref_device(dev)
    finally:
        lib.uvc_exit(ctx)


if __name__ == "__main__":
    sys.exit(main())
