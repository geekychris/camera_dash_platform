"""Radiometric helpers for FLIR Lepton (14-bit in 16-bit container).

Lepton 3.5 + PureThermal returns ``uint16`` per pixel where the value is
**centi-Kelvin** (Kelvin * 100). Convert to Celsius with
``(value / 100) - 273.15``.

For display we normalize the temperature range to 8-bit and apply an OpenCV
colormap; the radiometric matrix is kept on the side so the UI can show
per-pixel temperature on hover.
"""

from __future__ import annotations

import numpy as np

KELVIN_OFFSET = 273.15


def centikelvin_to_celsius(value: np.ndarray | int | float) -> np.ndarray | float:
    """Convert centi-Kelvin (Lepton native) to Celsius."""
    return (np.asarray(value, dtype=np.float32) / 100.0) - KELVIN_OFFSET


def normalize_for_display(radiometric: np.ndarray,
                          clip_low_pct: float = 1.0,
                          clip_high_pct: float = 99.0) -> np.ndarray:
    """Stretch the radiometric matrix to 8-bit using robust percentile clipping.

    Avoids one hot pixel washing out the whole scene.
    """
    lo = float(np.percentile(radiometric, clip_low_pct))
    hi = float(np.percentile(radiometric, clip_high_pct))
    if hi <= lo:
        hi = lo + 1.0
    norm = np.clip((radiometric.astype(np.float32) - lo) / (hi - lo), 0.0, 1.0)
    return (norm * 255.0).astype(np.uint8)


def colorize(radiometric: np.ndarray, colormap: int | None = None) -> np.ndarray:
    """Return a BGR uint8 (H, W, 3) image. Default colormap = INFERNO."""
    import cv2

    if colormap is None:
        colormap = cv2.COLORMAP_INFERNO
    gray = normalize_for_display(radiometric)
    return cv2.applyColorMap(gray, colormap)


def downsample_for_ws(radiometric: np.ndarray, max_dim: int = 320) -> np.ndarray:
    """Reduce matrix size for transmission over WebSocket; preserves dtype."""
    import cv2

    h, w = radiometric.shape[:2]
    if max(h, w) <= max_dim:
        return radiometric
    scale = max_dim / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    return cv2.resize(radiometric, (new_w, new_h), interpolation=cv2.INTER_AREA)
