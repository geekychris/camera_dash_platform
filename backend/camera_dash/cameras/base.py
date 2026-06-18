"""Camera abstraction. All camera drivers publish :class:`Frame` to a FrameBus."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CameraSpec:
    """Persistent description of a camera. Stored in DB; the runtime instantiates from it."""

    id: str                       # stable id, e.g. "uvc-0" or user-chosen
    kind: str                     # "uvc" | "flir_lepton"
    label: str = ""               # user-facing
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


class Camera(ABC):
    """Async camera driver. Reads frames from hardware and publishes to a FrameBus."""

    def __init__(self, spec: CameraSpec, frame_bus: Any) -> None:
        self.spec = spec
        self.frame_bus = frame_bus
        self._running = False

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def label(self) -> str:
        return self.spec.label or self.spec.id

    @property
    def is_running(self) -> bool:
        return self._running

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    def info(self) -> dict[str, Any]:
        """JSON-serializable description for the REST API."""
        return {
            "id": self.id,
            "kind": self.spec.kind,
            "label": self.label,
            "params": self.spec.params,
            "running": self.is_running,
            "is_thermal": self.spec.kind == "flir_lepton",
        }
