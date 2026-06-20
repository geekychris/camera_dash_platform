"""Point-cloud sink — dump a binary .ply on trigger.

Inputs:
    ``trigger`` — Event (required). Each event fires one capture, subject to
                  ``cooldown_s``.
    ``depth``   — DepthFrame (required). Source of XYZ.
    ``frame``   — Frame (optional). If present, its BGR is sampled and written
                  as per-vertex RGB so the cloud is colourised.

Output files land under ``data/point_clouds/<camera>/<iso>.ply``. Format is
PLY binary little-endian; readable by MeshLab, CloudCompare, Open3D, Blender.

Back-projection uses pinhole intrinsics; defaults match the Kinect v1 IR
camera factory calibration (close enough for most uses). Override via config
if you have a calibrated camera.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from ....pipeline.types import DepthFrame, Event, Frame, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)


class PointCloudSink(Node):
    TYPE_ID = "sink.point_cloud"
    UI_CATEGORY = "sink"
    INPUTS = (
        Port("trigger", PortType.EVENT),
        Port("depth", PortType.DEPTH_FRAME),
        Port("frame", PortType.FRAME, required=False),
    )
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "out_dir": {"type": "string", "default": "data/point_clouds",
                         "description": "Directory; created on first write"},
            "fx": {"type": "number", "default": 594.21,
                    "description": "Focal length in px (Kinect v1 default)"},
            "fy": {"type": "number", "default": 591.04,
                    "description": "Focal length in px (Kinect v1 default)"},
            "cx": {"type": "number", "default": 339.5,
                    "description": "Principal point x in px (Kinect v1 default)"},
            "cy": {"type": "number", "default": 242.7,
                    "description": "Principal point y in px (Kinect v1 default)"},
            "stride": {"type": "integer", "default": 1, "minimum": 1, "maximum": 8,
                       "description": "Down-sample by this factor — set 2 for ~75% smaller files"},
            "max_distance_mm": {"type": "integer", "default": 6000,
                                 "description": "Skip pixels farther than this"},
            "cooldown_s": {"type": "number", "default": 5.0, "minimum": 0.0,
                            "description": "Minimum seconds between writes; 0 = every trigger"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._last_write = 0.0

    async def process(self, **inputs: Any) -> dict[str, Any]:
        trigger: Event | None = inputs.get("trigger")
        depth: DepthFrame | None = inputs.get("depth")
        if trigger is None or depth is None:
            return {}
        cooldown = float(self.config.get("cooldown_s", 5.0))
        now = time.monotonic()
        if now - self._last_write < cooldown:
            return {}
        self._last_write = now

        fx = float(self.config.get("fx", 594.21))
        fy = float(self.config.get("fy", 591.04))
        cx = float(self.config.get("cx", 339.5))
        cy = float(self.config.get("cy", 242.7))
        stride = max(1, int(self.config.get("stride", 1)))
        max_mm = int(self.config.get("max_distance_mm", 6000))

        d = depth.data[::stride, ::stride]
        h, w = d.shape
        # Back-project: X = (u - cx) * Z / fx,  Y = (v - cy) * Z / fy.
        u_idx, v_idx = np.meshgrid(np.arange(w), np.arange(h))
        # Adjust intrinsics for the stride (pixel grid shrank).
        fx_s, fy_s, cx_s, cy_s = fx / stride, fy / stride, cx / stride, cy / stride
        z = d.astype(np.float32) / 1000.0  # mm -> metres
        valid = (d > 0) & (d <= max_mm)
        x = (u_idx - cx_s) * z / fx_s
        y = (v_idx - cy_s) * z / fy_s
        xyz = np.stack([x[valid], y[valid], z[valid]], axis=1)

        # Optional colour from the matched RGB frame. We resize to depth dims
        # first so per-vertex sampling is straightforward.
        frame: Frame | None = inputs.get("frame")
        rgb: np.ndarray | None = None
        if frame is not None and frame.data is not None:
            import cv2
            bgr = frame.data
            if bgr.shape[1] != depth.width or bgr.shape[0] != depth.height:
                bgr = cv2.resize(bgr, (depth.width, depth.height), interpolation=cv2.INTER_AREA)
            bgr = bgr[::stride, ::stride]
            rgb = bgr[..., ::-1][valid]  # BGR -> RGB

        out_dir = Path(self.config.get("out_dir", "data/point_clouds")) / depth.camera_id
        out_dir.mkdir(parents=True, exist_ok=True)
        ts_ns = depth.timestamp_ns or time.time_ns()
        out_path = out_dir / f"{ts_ns}.ply"
        _write_ply(out_path, xyz, rgb)
        log.info("point_cloud %s: wrote %d vertices to %s",
                 self.node_id, xyz.shape[0], out_path)
        return {}


def _write_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray | None) -> None:
    n = int(xyz.shape[0])
    has_color = rgb is not None
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}",
              "property float x", "property float y", "property float z"]
    if has_color:
        header += ["property uchar red", "property uchar green", "property uchar blue"]
    header += ["end_header", ""]
    with path.open("wb") as f:
        f.write("\n".join(header).encode("ascii"))
        if has_color:
            # numpy structured dtype keeps each record packed as 12 + 3 = 15 bytes.
            rec = np.empty(n, dtype=np.dtype([("xyz", "<f4", 3), ("rgb", "<u1", 3)]))
            rec["xyz"] = xyz.astype("<f4", copy=False)
            rec["rgb"] = rgb.astype("<u1", copy=False)
            f.write(rec.tobytes())
        else:
            f.write(xyz.astype("<f4", copy=False).tobytes())
