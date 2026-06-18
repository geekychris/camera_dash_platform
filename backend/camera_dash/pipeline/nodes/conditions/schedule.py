"""Schedule gate — only pass items through during configured time windows."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from ....pipeline.types import PortType
from ...node import Node, Port


def _parse_time(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


class ScheduleNode(Node):
    TYPE_ID = "condition.schedule"
    UI_CATEGORY = "condition"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = (
        Port("match", PortType.EVENT, required=False),
        Port("no_match", PortType.EVENT, required=False),
    )
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "windows": {"type": "array",
                         "items": {"type": "object", "properties": {
                             "start": {"type": "string", "default": "21:00",
                                        "description": "HH:MM local time"},
                             "end": {"type": "string", "default": "06:00"},
                             "days": {"type": "array",
                                       "items": {"type": "string",
                                                  "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
                                       "default": []},
                         }},
                         "default": [{"start": "00:00", "end": "23:59", "days": []}],
                         "description": "One or more time windows; matches if any window contains 'now'"},
        },
    }

    async def process(self, **inputs: Any) -> dict[str, Any]:
        payload = inputs.get("payload")
        if payload is None:
            return {}
        if self._is_open():
            return {"match": payload}
        return {"no_match": payload}

    def _is_open(self) -> bool:
        now = datetime.now()
        day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
        cur = now.time()
        for w in self.config.get("windows") or []:
            days = w.get("days") or []
            if days and day not in days:
                continue
            start = _parse_time(w.get("start", "00:00"))
            end = _parse_time(w.get("end", "23:59"))
            in_window = (start <= cur <= end) if start <= end else (cur >= start or cur <= end)
            if in_window:
                return True
        return False
