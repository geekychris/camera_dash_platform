"""Throttle node — pass through detections at most every ``interval_s`` seconds.

How the rate-limiting actually works: the node's ``process`` sleeps to enforce
the interval. While sleeping, upstream keeps emitting into the inbox queue,
which is bounded with drop-oldest semantics — so on the next read we get the
freshest detection set automatically.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ....pipeline.types import DetectionSet, PortType
from ...node import Node, Port


class ThrottleNode(Node):
    TYPE_ID = "transform.throttle"
    UI_CATEGORY = "transform"
    INPUTS = (Port("payload", PortType.DETECTIONS),)
    OUTPUTS = (Port("payload", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "interval_s": {"type": "number", "default": 5.0, "minimum": 0.05,
                            "description": "Minimum seconds between forwarded items"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._last = 0.0

    async def process(self, **inputs: Any) -> dict[str, Any]:
        payload: DetectionSet | None = inputs.get("payload")
        if payload is None:
            return {}
        interval = float(self.config.get("interval_s", 5.0))
        wait = max(0.0, interval - (time.monotonic() - self._last))
        if wait > 0:
            await asyncio.sleep(wait)
        self._last = time.monotonic()
        return {"payload": payload}
