from __future__ import annotations

import numpy as np

from camera_dash.utils.radiometric import centikelvin_to_celsius, downsample_for_ws


def test_centikelvin_to_celsius_known_value():
    # 100 C = 373.15 K = 37315 cK
    assert centikelvin_to_celsius(37315) == 100.0


def test_downsample_preserves_dtype():
    arr = np.zeros((480, 640), dtype=np.uint16)
    out = downsample_for_ws(arr, max_dim=160)
    assert out.dtype == np.uint16
    assert max(out.shape) == 160
