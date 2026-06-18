"""camera_dash — multi-camera dashboard + pluggable CV pipeline platform."""

__version__ = "0.1.0"


def _preload_brew_libs() -> None:
    """Force-load Homebrew GLib/GObject before PyGObject does.

    The python.org Python.app launcher strips DYLD_LIBRARY_PATH (SIP), so even
    with the env var set, ``import gi`` can pull a stale/partial libglib and
    crash with ``AssertionError`` deep in GLib overrides. Preloading the right
    dylibs with RTLD_GLOBAL fixes that without needing env vars.
    """
    import os
    import sys
    if sys.platform != "darwin":
        return
    import contextlib
    import ctypes
    for prefix in ("/opt/homebrew/lib", "/usr/local/lib"):
        if not os.path.isdir(prefix):
            continue
        for lib in ("libglib-2.0.0.dylib", "libgobject-2.0.0.dylib",
                    "libgio-2.0.0.dylib", "libgirepository-1.0.1.dylib"):
            path = os.path.join(prefix, lib)
            if os.path.exists(path):
                with contextlib.suppress(OSError):
                    ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
        # Also help GI find typelibs (idempotent if already set).
        os.environ.setdefault("GI_TYPELIB_PATH", os.path.join(prefix, "girepository-1.0"))
        return


_preload_brew_libs()
