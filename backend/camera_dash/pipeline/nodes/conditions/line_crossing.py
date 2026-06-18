"""Line-crossing condition — fire when a tracked object crosses a line in a
chosen direction. Needs upstream :class:`transform.tracker` so each detection
has a stable ``track_id``.

The line is two points; direction is the signed side change from the line's
normal. Set ``direction`` to ``"any"`` to fire on either crossing.
"""

from __future__ import annotations

from typing import Any

from ....pipeline.types import DetectionSet, Event, PortType
from ...node import Node, Port


def _side(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


class LineCrossingNode(Node):
    TYPE_ID = "condition.line_crossing"
    UI_CATEGORY = "condition"
    INPUTS = (Port("payload", PortType.DETECTIONS),)
    OUTPUTS = (
        Port("match", PortType.EVENT, required=False),
        Port("no_match", PortType.DETECTIONS, required=False),
    )
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["line"],
        "properties": {
            "line": {"type": "array", "items": {"type": "array", "items": {"type": "number"},
                                                 "minItems": 2, "maxItems": 2},
                      "minItems": 2, "maxItems": 2,
                      "description": "[[x1,y1], [x2,y2]] in pixel coords"},
            "direction": {"type": "string", "enum": ["any", "left_to_right", "right_to_left"],
                           "default": "any",
                           "description": "Direction along the line's normal"},
            "classes": {"type": "array", "items": {"type": "string"}, "default": []},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        # track_id -> previous side sign
        self._prev: dict[int, float] = {}

    async def process(self, **inputs: Any) -> dict[str, Any]:
        dets: DetectionSet | None = inputs.get("payload")
        if dets is None:
            return {}
        line = self.config["line"]
        a = (float(line[0][0]), float(line[0][1]))
        b = (float(line[1][0]), float(line[1][1]))
        direction = self.config.get("direction", "any")
        wanted = set(self.config.get("classes") or [])

        events: list[Event] = []
        seen_ids: set[int] = set()
        for d in dets.detections:
            if d.track_id is None:
                continue
            if wanted and d.label not in wanted:
                continue
            seen_ids.add(d.track_id)
            cx = d.bbox[0] + d.bbox[2] / 2
            cy = d.bbox[1] + d.bbox[3] / 2
            side = _side((cx, cy), a, b)
            prev = self._prev.get(d.track_id)
            self._prev[d.track_id] = side
            if prev is None or prev == 0 or side == 0:
                continue
            if (prev < 0) == (side < 0):
                continue  # no crossing this tick
            crossed = "left_to_right" if (prev < 0 and side > 0) else "right_to_left"
            if direction != "any" and direction != crossed:
                continue
            events.append(Event(
                pipeline_id=self.context.pipeline_id, node_id=self.node_id,
                camera_id=dets.camera_id, timestamp_ns=dets.timestamp_ns,
                kind="line_crossing",
                payload={"track_id": d.track_id, "label": d.label, "direction": crossed,
                         "line": line},
            ))

        # GC tracks no longer present
        for tid in list(self._prev):
            if tid not in seen_ids:
                del self._prev[tid]

        if not events:
            return {"no_match": dets}
        bus = self.context.event_bus
        if bus is not None:
            for e in events:
                bus.publish_nowait(e)
        return {"match": events[0]}
