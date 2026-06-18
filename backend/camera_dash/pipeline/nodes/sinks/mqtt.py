"""MQTT publisher sink. Accepts any payload type and serializes to JSON."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any

from ....pipeline.types import DetectionSet, Event, PortType
from ...node import Inbox, Node, Outbox, Port

log = logging.getLogger(__name__)


class MqttSink(Node):
    TYPE_ID = "sink.mqtt"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["broker", "topic"],
        "properties": {
            "broker": {"type": "string", "default": "tcp://localhost:1883",
                       "description": "tcp://host:port"},
            "topic": {"type": "string"},
            "qos": {"type": "integer", "enum": [0, 1, 2], "default": 0},
            "retain": {"type": "boolean", "default": False},
            "client_id": {"type": "string", "default": ""},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._client: Any = None

    async def setup(self) -> None:
        import paho.mqtt.client as mqtt  # type: ignore

        client_id = self.config.get("client_id") or ""
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        broker = self.config["broker"]
        if broker.startswith("tcp://"):
            broker = broker[len("tcp://"):]
        host, _, port = broker.partition(":")
        await asyncio.to_thread(self._client.connect, host, int(port or 1883), 60)
        self._client.loop_start()

    async def teardown(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:  # pragma: no cover
                pass

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        topic = self.config["topic"]
        qos = int(self.config.get("qos", 0))
        retain = bool(self.config.get("retain", False))
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue
            try:
                msg = json.dumps(_to_json(payload), default=str).encode()
                self._client.publish(topic, msg, qos=qos, retain=retain)
            except Exception:
                log.exception("mqtt publish failed")


def _to_json(payload: Any) -> Any:
    if isinstance(payload, Event):
        return {"pipeline_id": payload.pipeline_id, "node_id": payload.node_id,
                "camera_id": payload.camera_id, "timestamp_ns": payload.timestamp_ns,
                "kind": payload.kind, "payload": payload.payload}
    if isinstance(payload, DetectionSet):
        return {"camera_id": payload.camera_id, "timestamp_ns": payload.timestamp_ns,
                "source_node": payload.source_node,
                "detections": [
                    {"label": d.label, "score": d.score, "bbox": list(d.bbox),
                     "class_id": d.class_id, "track_id": d.track_id, "attrs": d.attrs}
                    for d in payload.detections
                ]}
    if is_dataclass(payload):
        return asdict(payload)
    return payload
