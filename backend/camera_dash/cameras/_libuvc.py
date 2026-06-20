"""Minimal libuvc ctypes wrapper for multi-PureThermal capture on macOS.

Why this exists: macOS AVFoundation (which GStreamer's ``avfvideosrc`` sits on
top of) refuses to start ISO streaming on more than one UVC camera that
shares the same VID:PID model — the second `pipeline.set_state(PLAYING)`
returns FAILURE. libuvc talks to USB directly via libusb, so it doesn't have
that limit. Trade-off: on macOS the kernel UVC driver (VDCAssistant) holds
the interface claim, so the backend must run as root (or `flir_lepton`
devices must be excluded via a kext blacklist) for libuvc to open the
device. This module exposes a small synchronous API:

    ctx = init()
    for entry in list_purethermal(ctx):            # sorted by (bus, address)
        handle = open_by_address(ctx, entry.bus, entry.address)
        stream = open_stream(handle, 160, 120, 9)
        while running:
            frame_u16 = stream_get_frame(stream, timeout_us=200_000)
            ...
        close_stream(stream); close_device(handle)
    exit(ctx)

Only the bits ``flir_lepton.py`` needs are wrapped. Anything more exotic
(callback streaming, format probing, XU controls on the same handle) is left
to the caller via the raw ``lib`` attribute.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import sys
import threading
from ctypes import (
    POINTER, Structure, byref, c_char_p, c_int, c_size_t, c_uint8, c_uint16, c_uint32,
    c_uint64, c_void_p,
)
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

PURETHERMAL_VID = 0x1E4E
PURETHERMAL_PID = 0x0100

# enum uvc_frame_format — only the ones we care about.
UVC_FRAME_FORMAT_GRAY16 = 11

# enum uvc_error_t values we surface.
UVC_SUCCESS = 0
UVC_ERROR_ACCESS = -3  # The classic macOS VDCAssistant claim error.
UVC_ERROR_NOT_FOUND = -5
UVC_ERROR_TIMEOUT = -10


def _load() -> ctypes.CDLL:
    path = ctypes.util.find_library("uvc")
    if not path:
        for cand in (
            "/opt/homebrew/lib/libuvc.dylib",
            "/usr/local/lib/libuvc.dylib",
            "/usr/lib/libuvc.so.0",
            "/usr/lib/x86_64-linux-gnu/libuvc.so.0",
        ):
            if os.path.exists(cand):
                path = cand
                break
    if not path:
        raise RuntimeError(
            "libuvc not found — install with `brew install libuvc` (macOS) or "
            "`apt install libuvc-dev` (Linux).")
    return ctypes.CDLL(path)


# Forward-declared opaque types.
class uvc_context(Structure): pass
class uvc_device(Structure): pass
class uvc_device_handle(Structure): pass
class uvc_stream_handle(Structure): pass


class _Timeval(Structure):
    _fields_ = [("tv_sec", c_uint64), ("tv_usec", c_uint64)]


class _Timespec(Structure):
    _fields_ = [("tv_sec", c_uint64), ("tv_nsec", c_uint64)]


# struct uvc_frame { ... } — must match libuvc/libuvc.h byte-for-byte.
class uvc_frame(Structure):
    _fields_ = [
        ("data", c_void_p),
        ("data_bytes", c_size_t),
        ("width", c_uint32),
        ("height", c_uint32),
        ("frame_format", c_int),
        ("step", c_size_t),
        ("sequence", c_uint32),
        ("capture_time", _Timeval),
        ("capture_time_finished", _Timespec),
        ("source", POINTER(uvc_device_handle)),
        ("library_owns_data", c_uint8),
        ("metadata", c_void_p),
        ("metadata_bytes", c_size_t),
    ]


class uvc_device_descriptor(Structure):
    _fields_ = [
        ("idVendor", c_uint16),
        ("idProduct", c_uint16),
        ("bcdUVC", c_uint16),
        ("serialNumber", c_char_p),
        ("manufacturer", c_char_p),
        ("product", c_char_p),
    ]


class uvc_stream_ctrl(Structure):
    # Opaque to us — libuvc fills it. Size derived from the header; round up to be safe.
    _fields_ = [("_blob", c_uint8 * 64)]


_lib_lock = threading.Lock()
_lib: ctypes.CDLL | None = None


def _get_lib() -> ctypes.CDLL:
    global _lib
    with _lib_lock:
        if _lib is None:
            _lib = _load()
            _setup_signatures(_lib)
        return _lib


def _setup_signatures(lib: ctypes.CDLL) -> None:
    lib.uvc_init.argtypes = [POINTER(POINTER(uvc_context)), c_void_p]
    lib.uvc_init.restype = c_int
    lib.uvc_exit.argtypes = [POINTER(uvc_context)]
    lib.uvc_exit.restype = None

    lib.uvc_get_device_list.argtypes = [POINTER(uvc_context), POINTER(POINTER(POINTER(uvc_device)))]
    lib.uvc_get_device_list.restype = c_int
    lib.uvc_free_device_list.argtypes = [POINTER(POINTER(uvc_device)), c_uint8]
    lib.uvc_free_device_list.restype = None

    lib.uvc_get_device_descriptor.argtypes = [POINTER(uvc_device), POINTER(POINTER(uvc_device_descriptor))]
    lib.uvc_get_device_descriptor.restype = c_int
    lib.uvc_free_device_descriptor.argtypes = [POINTER(uvc_device_descriptor)]
    lib.uvc_free_device_descriptor.restype = None

    lib.uvc_get_bus_number.argtypes = [POINTER(uvc_device)]
    lib.uvc_get_bus_number.restype = c_uint8
    lib.uvc_get_device_address.argtypes = [POINTER(uvc_device)]
    lib.uvc_get_device_address.restype = c_uint8

    lib.uvc_ref_device.argtypes = [POINTER(uvc_device)]
    lib.uvc_ref_device.restype = c_int
    lib.uvc_unref_device.argtypes = [POINTER(uvc_device)]
    lib.uvc_unref_device.restype = None

    lib.uvc_open.argtypes = [POINTER(uvc_device), POINTER(POINTER(uvc_device_handle))]
    lib.uvc_open.restype = c_int
    lib.uvc_close.argtypes = [POINTER(uvc_device_handle)]
    lib.uvc_close.restype = None

    lib.uvc_get_stream_ctrl_format_size.argtypes = [
        POINTER(uvc_device_handle), POINTER(uvc_stream_ctrl), c_int, c_int, c_int, c_int,
    ]
    lib.uvc_get_stream_ctrl_format_size.restype = c_int

    lib.uvc_stream_open_ctrl.argtypes = [
        POINTER(uvc_device_handle), POINTER(POINTER(uvc_stream_handle)), POINTER(uvc_stream_ctrl),
    ]
    lib.uvc_stream_open_ctrl.restype = c_int
    lib.uvc_stream_start.argtypes = [POINTER(uvc_stream_handle), c_void_p, c_void_p, c_uint8]
    lib.uvc_stream_start.restype = c_int
    lib.uvc_stream_get_frame.argtypes = [POINTER(uvc_stream_handle), POINTER(POINTER(uvc_frame)), c_uint32]
    lib.uvc_stream_get_frame.restype = c_int
    lib.uvc_stream_stop.argtypes = [POINTER(uvc_stream_handle)]
    lib.uvc_stream_stop.restype = c_int
    lib.uvc_stream_close.argtypes = [POINTER(uvc_stream_handle)]
    lib.uvc_stream_close.restype = None

    lib.uvc_strerror.argtypes = [c_int]
    lib.uvc_strerror.restype = c_char_p


@dataclass(frozen=True)
class PureThermalEntry:
    """A PureThermal device available on the bus, with a stable identifier."""

    index: int          # Index into the sorted-by-(bus, address) list — stable per session.
    bus: int
    address: int
    serial: str | None  # Often None unless the FW exposes it.


def uvc_strerror(code: int) -> str:
    s = _get_lib().uvc_strerror(code)
    return (s.decode() if s else f"uvc_error {code}")


def init() -> Any:
    lib = _get_lib()
    ctx = POINTER(uvc_context)()
    r = lib.uvc_init(byref(ctx), None)
    if r != UVC_SUCCESS:
        raise RuntimeError(f"uvc_init failed: {uvc_strerror(r)}")
    return ctx


def exit_(ctx: Any) -> None:
    lib = _get_lib()
    if ctx:
        lib.uvc_exit(ctx)


def list_purethermal(ctx: Any) -> list[PureThermalEntry]:
    """Enumerate every PureThermal/Lepton currently on USB.

    Returns entries sorted by (bus number, device address) so a given
    ``index`` is stable across calls within the same OS session — that's the
    contract ``flir_lepton`` relies on to pin a specific camera.
    """
    lib = _get_lib()
    list_head = POINTER(POINTER(uvc_device))()
    r = lib.uvc_get_device_list(ctx, byref(list_head))
    if r != UVC_SUCCESS:
        raise RuntimeError(f"uvc_get_device_list failed: {uvc_strerror(r)}")
    try:
        rows: list[PureThermalEntry] = []
        i = 0
        while list_head[i]:
            dev = list_head[i]
            i += 1
            desc_ptr = POINTER(uvc_device_descriptor)()
            if lib.uvc_get_device_descriptor(dev, byref(desc_ptr)) != UVC_SUCCESS:
                continue
            try:
                desc = desc_ptr.contents
                if desc.idVendor != PURETHERMAL_VID or desc.idProduct != PURETHERMAL_PID:
                    continue
                serial = desc.serialNumber.decode() if desc.serialNumber else None
            finally:
                lib.uvc_free_device_descriptor(desc_ptr)
            rows.append((
                int(lib.uvc_get_bus_number(dev)),
                int(lib.uvc_get_device_address(dev)),
                serial,
            ))
        rows.sort(key=lambda t: (t[0], t[1]))
        return [PureThermalEntry(index=idx, bus=b, address=a, serial=s)
                for idx, (b, a, s) in enumerate(rows)]
    finally:
        lib.uvc_free_device_list(list_head, 1)  # unref devices on free


def open_by_address(ctx: Any, bus: int, address: int) -> Any:
    """Find the device matching (bus, address) and open it.

    Returns an opaque handle pointer to be passed to ``open_stream`` /
    ``close_device``. Raises if the device isn't present or the open fails
    (most commonly UVC_ERROR_ACCESS when VDCAssistant holds the claim on
    macOS — backend must run as root in that case).
    """
    lib = _get_lib()
    list_head = POINTER(POINTER(uvc_device))()
    r = lib.uvc_get_device_list(ctx, byref(list_head))
    if r != UVC_SUCCESS:
        raise RuntimeError(f"uvc_get_device_list failed: {uvc_strerror(r)}")
    matched = None
    try:
        i = 0
        while list_head[i]:
            dev = list_head[i]
            i += 1
            if (int(lib.uvc_get_bus_number(dev)) == bus
                    and int(lib.uvc_get_device_address(dev)) == address):
                matched = dev
                lib.uvc_ref_device(matched)  # keep alive past free_device_list
                break
        if matched is None:
            raise RuntimeError(f"libuvc: no device at bus={bus} addr={address}")
    finally:
        lib.uvc_free_device_list(list_head, 1)

    handle = POINTER(uvc_device_handle)()
    r = lib.uvc_open(matched, byref(handle))
    if r != UVC_SUCCESS:
        lib.uvc_unref_device(matched)
        if r == UVC_ERROR_ACCESS:
            raise PermissionError(
                f"uvc_open failed: {uvc_strerror(r)}. On macOS this is normally "
                f"VDCAssistant holding the kernel UVC claim — run the backend as "
                f"root, or install a kext exclusion for VID 0x{PURETHERMAL_VID:04x}.")
        raise RuntimeError(f"uvc_open failed: {uvc_strerror(r)}")
    # uvc_open holds its own ref via the handle; we can drop ours.
    lib.uvc_unref_device(matched)
    return handle


def close_device(handle: Any) -> None:
    lib = _get_lib()
    if handle:
        lib.uvc_close(handle)


def open_stream(handle: Any, width: int, height: int, fps: int) -> Any:
    """Negotiate Y16 streaming and open a stream handle.

    Returns ``(stream_handle, ctrl_struct)`` — keep both alive until
    ``close_stream``; libuvc reads ``ctrl_struct`` during streaming.
    """
    lib = _get_lib()
    ctrl = uvc_stream_ctrl()
    r = lib.uvc_get_stream_ctrl_format_size(
        handle, byref(ctrl), UVC_FRAME_FORMAT_GRAY16, width, height, fps,
    )
    if r != UVC_SUCCESS:
        raise RuntimeError(f"uvc_get_stream_ctrl_format_size failed: {uvc_strerror(r)}")
    strm = POINTER(uvc_stream_handle)()
    r = lib.uvc_stream_open_ctrl(handle, byref(strm), byref(ctrl))
    if r != UVC_SUCCESS:
        raise RuntimeError(f"uvc_stream_open_ctrl failed: {uvc_strerror(r)}")
    # NULL callback + flags=0 → synchronous mode; we'll poll via uvc_stream_get_frame.
    r = lib.uvc_stream_start(strm, None, None, 0)
    if r != UVC_SUCCESS:
        lib.uvc_stream_close(strm)
        raise RuntimeError(f"uvc_stream_start failed: {uvc_strerror(r)}")
    # Stash ctrl on the strm wrapper so the caller doesn't have to thread it through.
    return _StreamRef(strm=strm, ctrl=ctrl)


def stream_get_frame(stream: Any, timeout_us: int = 200_000) -> np.ndarray | None:
    """Pull the next Y16 frame from a streaming handle.

    Returns a (H, W) ``uint16`` array, or ``None`` on timeout — the caller
    should treat timeout as "try again", not an error, unless many in a row.
    """
    lib = _get_lib()
    frame_ptr = POINTER(uvc_frame)()
    r = lib.uvc_stream_get_frame(stream.strm, byref(frame_ptr), timeout_us)
    if r == UVC_ERROR_TIMEOUT:
        return None
    if r != UVC_SUCCESS:
        raise RuntimeError(f"uvc_stream_get_frame failed: {uvc_strerror(r)}")
    if not frame_ptr:
        return None
    f = frame_ptr.contents
    w = int(f.width)
    h = int(f.height)
    nbytes = int(f.data_bytes)
    expected = w * h * 2
    if nbytes < expected:
        log.warning("libuvc frame shorter than expected: %d < %d (w=%d h=%d)",
                    nbytes, expected, w, h)
        return None
    buf = (c_uint8 * expected).from_address(int(f.data))
    return np.frombuffer(buf, dtype="<u2").reshape(h, w).copy()


def close_stream(stream: Any) -> None:
    lib = _get_lib()
    if stream and stream.strm:
        lib.uvc_stream_stop(stream.strm)
        lib.uvc_stream_close(stream.strm)


class _StreamRef:
    """Holds the stream handle pointer + its ctrl struct (kept alive together)."""

    __slots__ = ("strm", "ctrl")

    def __init__(self, strm: Any, ctrl: Any) -> None:
        self.strm = strm
        self.ctrl = ctrl


def available() -> bool:
    """True if libuvc can be loaded — let flir_lepton fall back gracefully."""
    try:
        _get_lib()
        return True
    except Exception:
        return False


# Module-level "is this macOS?" hint so callers don't need to import platform.
IS_DARWIN = sys.platform == "darwin"
