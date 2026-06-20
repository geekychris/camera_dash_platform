"""Pipeline data types shared between nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np


class PixelFormat(StrEnum):
    RGB = "rgb"
    BGR = "bgr"
    GRAY = "gray"
    THERMAL14 = "thermal14"  # 16-bit container holding 14-bit Lepton radiometric


@dataclass(slots=True)
class Frame:
    """A single video frame, optionally with a co-registered radiometric matrix."""

    camera_id: str
    timestamp_ns: int
    width: int
    height: int
    pixel_format: PixelFormat
    data: np.ndarray  # (H, W, C) for color, (H, W) for gray/thermal
    radiometric: np.ndarray | None = None  # (H, W) int16, centi-Kelvin (0.01 K)
    metadata: dict[str, Any] = field(default_factory=dict)

    def shape(self) -> tuple[int, int]:
        return self.height, self.width

    def temperature_celsius(self, x: int, y: int) -> float | None:
        """Return per-pixel Celsius if a radiometric matrix is present."""
        if self.radiometric is None:
            return None
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return float(self.radiometric[y, x]) / 100.0 - 273.15


@dataclass(slots=True)
class DepthFrame:
    """A depth map co-registered with a color frame.

    ``data`` is a (H, W) ``uint16`` array of distances in millimetres. ``0``
    means "no reading" (out-of-range, IR shadow, or sensor noise) — downstream
    nodes must treat zeros as invalid, not as zero-distance.
    """

    camera_id: str
    timestamp_ns: int
    width: int
    height: int
    data: np.ndarray  # (H, W) uint16, millimetres; 0 == invalid
    fov_deg: tuple[float, float] | None = None  # (horizontal, vertical) in degrees, if known
    metadata: dict[str, Any] = field(default_factory=dict)

    def shape(self) -> tuple[int, int]:
        return self.height, self.width

    def distance_mm(self, x: int, y: int) -> int | None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        v = int(self.data[y, x])
        return v if v > 0 else None


@dataclass(slots=True)
class Detection:
    label: str
    score: float
    bbox: tuple[float, float, float, float]  # (x, y, w, h) in pixels
    class_id: int | None = None
    track_id: int | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DetectionSet:
    """Detections attached to a specific frame."""

    camera_id: str
    timestamp_ns: int
    detections: list[Detection] = field(default_factory=list)
    source_node: str = ""

    def __iter__(self):
        return iter(self.detections)

    def __len__(self) -> int:
        return len(self.detections)


@dataclass(slots=True)
class Event:
    """Generic event flowing toward sinks (MQTT, Kafka, etc.)."""

    pipeline_id: str
    node_id: str
    camera_id: str | None
    timestamp_ns: int
    kind: str  # e.g. "detection", "temperature_exceeded"
    payload: dict[str, Any] = field(default_factory=dict)


class PortType(StrEnum):
    """Port types determine queue semantics in the engine."""

    FRAME = "frame"             # drop-oldest, very small queue (live video)
    DEPTH_FRAME = "depth_frame"  # drop-oldest, parallel depth stream from Kinect/OAK
    DETECTIONS = "detections"   # small queue, drop-oldest
    EVENT = "event"             # keep all, never drop (alerts)
    TRIGGER = "trigger"         # boolean/payload pulses, keep all


PORT_TYPE_QUEUE_DEPTH = {
    PortType.FRAME: 2,
    PortType.DEPTH_FRAME: 2,
    PortType.DETECTIONS: 4,
    PortType.EVENT: 256,
    PortType.TRIGGER: 64,
}

PORT_TYPE_DROP_OLDEST = {
    PortType.FRAME: True,
    PortType.DEPTH_FRAME: True,
    PortType.DETECTIONS: True,
    PortType.EVENT: False,
    PortType.TRIGGER: False,
}
