"""Persist Event payloads to the SQLite events table."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ....pipeline.types import DetectionSet, Event, PortType
from ....storage import models
from ....storage.db import get_session
from ...node import Inbox, Node, Outbox, Port


class SqliteEventSink(Node):
    TYPE_ID = "sink.sqlite"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "kind_override": {"type": "string", "default": "",
                              "description": "Force a `kind` value; defaults to event.kind or 'detection'"},
        },
    }

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue
            await self._store(payload)

    async def _store(self, payload: Any) -> None:
        kind = self.config.get("kind_override") or ""
        async with get_session() as s:
            if isinstance(payload, Event):
                s.add(models.Event(
                    pipeline_id=payload.pipeline_id, node_id=payload.node_id,
                    camera_id=payload.camera_id, timestamp=datetime.now(UTC),
                    kind=kind or payload.kind, payload=payload.payload,
                ))
            elif isinstance(payload, DetectionSet):
                s.add(models.Event(
                    pipeline_id=self.context.pipeline_id, node_id=self.node_id,
                    camera_id=payload.camera_id, timestamp=datetime.now(UTC),
                    kind=kind or "detection",
                    payload={"count": len(payload.detections),
                             "labels": list({d.label for d in payload.detections})},
                ))
            await s.commit()
