"""Console log sink.

Writes incoming payload via Python ``logging`` at the configured level. Useful
for during-development visibility into a pipeline without standing up MQTT/Kafka.
The actual ``stdout`` redirection comes from however the backend is launched —
uvicorn's logger emits to stdout by default.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from ....pipeline.types import DetectionSet, Event, PortType
from ...node import Inbox, Node, Outbox, Port
from .mqtt import _to_json


class ConsoleSink(Node):
    """Log payloads to the Python logging system (a.k.a. backend stdout)."""

    TYPE_ID = "sink.console"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "level": {"type": "string", "enum": ["debug", "info", "warning", "error"],
                       "default": "info"},
            "format": {"type": "string", "enum": ["pretty", "json", "compact"],
                        "default": "pretty",
                        "description": "pretty=multi-line, json=one-line JSON, compact=summary"},
            "prefix": {"type": "string", "default": ""},
            "broadcast": {"type": "boolean", "default": True,
                          "description": "Also publish to /api/events/stream so dashboard log tiles can show it"},
        },
    }

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        log = logging.getLogger(f"camera_dash.pipeline.{self.context.pipeline_id}.{self.node_id}")
        level = getattr(logging, self.config.get("level", "info").upper(), logging.INFO)
        fmt = self.config.get("format", "pretty")
        prefix = self.config.get("prefix", "")
        broadcast = bool(self.config.get("broadcast", True))
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue
            data = _to_json(payload)
            if fmt == "json":
                msg = f"{prefix}{json.dumps(data, default=str, separators=(',', ':'))}"
            elif fmt == "compact":
                msg = f"{prefix}{_summarize(data)}"
            else:  # pretty
                msg = f"{prefix}\n{json.dumps(data, default=str, indent=2)}"
            log.log(level, msg)

            # Also fan to the EventBus so dashboard log tiles can subscribe via SSE
            bus = self.context.event_bus
            if broadcast and bus is not None:
                bus.publish_nowait(_to_event(payload, self.context.pipeline_id, self.node_id, msg))


def _to_event(payload: Any, pipeline_id: str, node_id: str, formatted: str) -> Event:
    cam: str | None = None
    ts_ns: int = time.time_ns()
    if isinstance(payload, Event):
        return payload  # already an event — pass through
    if isinstance(payload, DetectionSet):
        cam = payload.camera_id
        ts_ns = payload.timestamp_ns
        return Event(
            pipeline_id=pipeline_id, node_id=node_id, camera_id=cam, timestamp_ns=ts_ns,
            kind="console",
            payload={
                "count": len(payload.detections),
                "labels": [d.label for d in payload.detections],
                "detections": [
                    {"label": d.label, "score": d.score, "bbox": list(d.bbox)}
                    for d in payload.detections
                ],
                "formatted": formatted,
            },
        )
    return Event(
        pipeline_id=pipeline_id, node_id=node_id, camera_id=cam, timestamp_ns=ts_ns,
        kind="console", payload={"value": repr(payload), "formatted": formatted},
    )


def _summarize(data: Any) -> str:
    if isinstance(data, dict):
        if "detections" in data:
            cam = data.get("camera_id", "?")
            labels = [d.get("label") for d in data.get("detections", [])]
            return f"camera={cam} n={len(labels)} labels={labels}"
        if "kind" in data:
            return (f"kind={data.get('kind')} camera={data.get('camera_id', '?')} "
                    f"payload={data.get('payload', {})}")
    return repr(data)
