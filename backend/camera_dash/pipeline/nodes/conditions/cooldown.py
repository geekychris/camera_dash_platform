"""Cooldown / debounce — drop events that arrive within ``cooldown_s`` of the last passed one."""

from __future__ import annotations

import time
from typing import Any

from ....pipeline.types import Event, PortType
from ...node import Node, Port


class CooldownNode(Node):
    TYPE_ID = "condition.cooldown"
    UI_CATEGORY = "condition"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = (
        Port("match", PortType.EVENT, required=False),
        Port("no_match", PortType.EVENT, required=False),
    )
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "cooldown_s": {"type": "number", "default": 60.0, "minimum": 0.1},
            "scope": {"type": "string",
                       "enum": ["global", "per_kind", "per_camera", "per_camera_kind"],
                       "default": "per_camera_kind",
                       "description": "Group key for the cooldown timer"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._last: dict[str, float] = {}

    async def process(self, **inputs: Any) -> dict[str, Any]:
        payload = inputs.get("payload")
        if payload is None:
            return {}
        cooldown = float(self.config.get("cooldown_s", 60.0))
        scope = self.config.get("scope", "per_camera_kind")
        key = self._key(payload, scope)
        now = time.monotonic()
        last = self._last.get(key, 0.0)
        if (now - last) < cooldown:
            return {"no_match": payload}
        self._last[key] = now
        return {"match": payload}

    @staticmethod
    def _key(payload: Any, scope: str) -> str:
        if isinstance(payload, Event):
            cam = payload.camera_id or "?"
            kind = payload.kind
            if scope == "global":
                return "*"
            if scope == "per_kind":
                return kind
            if scope == "per_camera":
                return cam
            return f"{cam}/{kind}"
        return "*"
