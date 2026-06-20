"""CameraManager — lifecycle owner for all configured cameras.

Holds a registry keyed by camera id, starts/stops drivers, and exposes a
JSON-friendly view for the REST API. Camera specs are persisted in the DB
(``storage.models.Camera``) but the manager itself works on plain
:class:`CameraSpec` objects so it can be exercised without a DB.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..settings import Settings
from ..streaming.frame_bus import FrameBus
from .base import Camera, CameraSpec
from .flir_lepton import FlirLeptonCamera
from .kinect_v1 import KinectV1Camera
from .oak import OakCamera
from .rtsp import RtspCamera
from .screen import ScreenCamera
from .uvc import UvcCamera
from .uvc import list_devices as list_uvc_devices

log = logging.getLogger(__name__)


_DRIVERS: dict[str, type[Camera]] = {
    "uvc": UvcCamera,
    "flir_lepton": FlirLeptonCamera,
    "rtsp": RtspCamera,
    "screen": ScreenCamera,
    "oak": OakCamera,
    "kinect_v1": KinectV1Camera,
}


class CameraManager:
    def __init__(self, settings: Settings, frame_bus: FrameBus) -> None:
        self.settings = settings
        self.frame_bus = frame_bus
        self._cameras: dict[str, Camera] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Load persisted cameras from storage and start the enabled ones."""
        from ..storage import models
        from ..storage.db import get_session

        async with get_session() as s:
            rows = (await s.execute(models.Camera.select_all())).scalars().all()
        for row in rows:
            spec = CameraSpec(
                id=row.id, kind=row.kind, label=row.label,
                params=row.params or {}, enabled=row.enabled,
            )
            if spec.enabled:
                try:
                    await self.add(spec, persist=False)
                except Exception:
                    log.exception("failed to start camera %s", spec.id)

    async def stop(self) -> None:
        async with self._lock:
            await asyncio.gather(*(c.stop() for c in self._cameras.values()),
                                 return_exceptions=True)
            self._cameras.clear()

    # ----- CRUD -----

    def list(self) -> list[dict[str, Any]]:
        return [c.info() for c in self._cameras.values()]

    def get(self, camera_id: str) -> Camera | None:
        return self._cameras.get(camera_id)

    async def add(self, spec: CameraSpec, persist: bool = True) -> Camera:
        if spec.kind not in _DRIVERS:
            raise ValueError(f"unknown camera kind: {spec.kind}")
        async with self._lock:
            if spec.id in self._cameras:
                raise ValueError(f"camera {spec.id} already registered")
            cam = _DRIVERS[spec.kind](spec, self.frame_bus)
            await cam.start()
            self._cameras[spec.id] = cam
        if persist:
            await self._persist(spec)
        return cam

    async def remove(self, camera_id: str, persist: bool = True) -> None:
        async with self._lock:
            cam = self._cameras.pop(camera_id, None)
            if cam:
                await cam.stop()
        if persist:
            await self._unpersist(camera_id)

    async def update_label(self, camera_id: str, label: str) -> None:
        cam = self._cameras.get(camera_id)
        if cam is None:
            raise KeyError(camera_id)
        cam.spec.label = label
        await self._persist(cam.spec)

    # ----- Discovery -----

    @staticmethod
    def discover() -> list[dict[str, Any]]:
        return list_uvc_devices()

    @staticmethod
    def discover_kinects() -> list[dict[str, Any]]:
        """Enumerate Kinect 360 (v1) devices via libfreenect.

        Returns ``[{"index": i, "name": "Kinect 360 #<i>", "serial": "..."}]``
        — libfreenect only exposes a count + per-device serials, no friendly
        names — so we synthesize the name from the index.
        """
        try:
            import freenect  # type: ignore
        except ImportError:
            return []
        out: list[dict[str, Any]] = []
        try:
            ctx = freenect.init()
            n = freenect.num_devices(ctx)
            for i in range(n):
                entry: dict[str, Any] = {"index": i, "name": f"Kinect 360 #{i}"}
                try:
                    dev = freenect.open_device(ctx, i)
                    if dev is not None:
                        serial = getattr(freenect, "camera_get_serial", lambda *_: None)(dev)
                        if serial:
                            entry["serial"] = str(serial)
                        freenect.close_device(dev)
                except Exception:  # pragma: no cover
                    log.debug("kinect %d serial lookup failed", i, exc_info=True)
                out.append(entry)
            try:
                freenect.shutdown(ctx)
            except Exception:  # pragma: no cover
                pass
        except Exception:  # pragma: no cover
            log.exception("kinect enumeration failed")
        return out

    # ----- Persistence helpers -----

    async def _persist(self, spec: CameraSpec) -> None:
        from ..storage import models
        from ..storage.db import get_session
        async with get_session() as s:
            await models.Camera.upsert(s, spec)
            await s.commit()

    async def _unpersist(self, camera_id: str) -> None:
        from ..storage import models
        from ..storage.db import get_session
        async with get_session() as s:
            await models.Camera.delete(s, camera_id)
            await s.commit()
