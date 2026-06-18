"""Polygon zone condition — fires when tracked objects enter / dwell / leave a zone.

Designed to sit after :class:`transform.tracker` so each detection has a
stable ``track_id``. Without tracking, "entered" would fire every frame.

Config:
    polygon            list of [x, y] pixel coordinates (ring; auto-closes)
    fire_on            "enter"  (default) — one event per track when it first crosses in
                       "leave"            — one event when track exits
                       "dwell"            — one event when a track has been inside for `dwell_s` seconds
    dwell_s            seconds, used when fire_on=dwell (default 5)
    classes            optional whitelist of labels to consider (e.g. ["person"])

Outputs:
    match              Event when the trigger fires (routed to sink.mqtt, sink.recorder, etc.)
    no_match           the passthrough DetectionSet so downstream still gets boxes
"""

from __future__ import annotations

import time
from typing import Any

import cv2
import numpy as np

from ....pipeline.types import DetectionSet, Event, PortType
from ...node import Node, Port


class ZoneNode(Node):
    TYPE_ID = "condition.zone"
    UI_CATEGORY = "condition"
    INPUTS = (Port("payload", PortType.DETECTIONS),)
    OUTPUTS = (
        Port("match", PortType.EVENT, required=False),
        Port("no_match", PortType.DETECTIONS, required=False),
    )
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["polygon"],
        "properties": {
            "polygon": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "minItems": 3,
                "description": "[[x,y], [x,y], ...] in pixel coords; auto-closes",
            },
            "fire_on": {"type": "string", "enum": ["enter", "leave", "dwell"], "default": "enter"},
            "dwell_s": {"type": "number", "default": 5.0},
            "classes": {"type": "array", "items": {"type": "string"}, "default": []},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        # track_id -> {"first_seen": float, "in_zone": bool}
        self._state: dict[int, dict[str, Any]] = {}
        self._fired_enter: set[int] = set()
        self._fired_dwell: set[int] = set()

    async def process(self, **inputs: Any) -> dict[str, Any]:
        dets: DetectionSet | None = inputs.get("payload")
        if dets is None:
            return {}

        poly = np.array(self.config["polygon"], dtype=np.int32)
        classes_filter = set(self.config.get("classes") or [])
        fire_on = self.config.get("fire_on", "enter")
        dwell_s = float(self.config.get("dwell_s", 5.0))
        now = time.monotonic()

        # Compute which tracks are currently in the zone
        in_zone_now: set[int] = set()
        last_in_zone: dict[int, dict[str, Any]] = {}
        for d in dets.detections:
            if d.track_id is None:
                continue
            if classes_filter and d.label not in classes_filter:
                continue
            cx = d.bbox[0] + d.bbox[2] / 2
            cy = d.bbox[1] + d.bbox[3] / 2
            inside = cv2.pointPolygonTest(poly, (float(cx), float(cy)), False) >= 0
            if inside:
                in_zone_now.add(d.track_id)
                last_in_zone[d.track_id] = {"label": d.label, "score": d.score,
                                              "bbox": list(d.bbox)}

        # Maintain per-track state
        events: list[Event] = []
        prev_in_zone = {tid for tid, st in self._state.items() if st.get("in_zone")}
        all_tracks = in_zone_now | prev_in_zone

        for tid in all_tracks:
            st = self._state.setdefault(tid, {"first_seen": now, "in_zone": False})
            was_in = st["in_zone"]
            is_in = tid in in_zone_now
            st["in_zone"] = is_in
            if is_in and not was_in:
                # entered
                st["first_seen"] = now
                self._fired_dwell.discard(tid)
                if fire_on == "enter" and tid not in self._fired_enter:
                    self._fired_enter.add(tid)
                    events.append(self._event(dets, tid, "zone_enter", last_in_zone.get(tid)))
            elif (not is_in) and was_in:
                # left
                self._fired_enter.discard(tid)
                if fire_on == "leave":
                    events.append(self._event(dets, tid, "zone_leave", None))
                self._state.pop(tid, None)
            elif is_in and fire_on == "dwell" and tid not in self._fired_dwell:
                if (now - st["first_seen"]) >= dwell_s:
                    self._fired_dwell.add(tid)
                    payload = last_in_zone.get(tid) or {}
                    payload["dwell_s"] = now - st["first_seen"]
                    events.append(self._event(dets, tid, "zone_dwell", payload))

        # Garbage-collect tracks no longer being seen at all
        stale = [tid for tid in self._state if tid not in all_tracks]
        for tid in stale:
            self._state.pop(tid, None)
            self._fired_enter.discard(tid)
            self._fired_dwell.discard(tid)

        out: dict[str, Any] = {"no_match": dets}
        if events:
            # If multiple events fire this tick, emit them all by publishing
            # extras directly to the event_bus and returning the first via the port.
            bus = self.context.event_bus
            for evt in events[1:]:
                if bus is not None:
                    bus.publish_nowait(evt)
            out["match"] = events[0]
            if bus is not None:
                bus.publish_nowait(events[0])
        return out

    def _event(self, dets: DetectionSet, track_id: int, kind: str,
               extra: dict[str, Any] | None) -> Event:
        payload: dict[str, Any] = {"track_id": track_id, "polygon": self.config["polygon"]}
        if extra:
            payload.update(extra)
        return Event(
            pipeline_id=self.context.pipeline_id, node_id=self.node_id,
            camera_id=dets.camera_id, timestamp_ns=dets.timestamp_ns,
            kind=kind, payload=payload,
        )
