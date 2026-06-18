"""Kafka producer sink (aiokafka)."""

from __future__ import annotations

import json
import logging
from typing import Any

from ....pipeline.types import PortType
from ...node import Inbox, Node, Outbox, Port
from .mqtt import _to_json

log = logging.getLogger(__name__)


class KafkaSink(Node):
    TYPE_ID = "sink.kafka"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["bootstrap_servers", "topic"],
        "properties": {
            "bootstrap_servers": {"type": "string", "default": "localhost:9092"},
            "topic": {"type": "string"},
            "client_id": {"type": "string", "default": "camera_dash"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._producer: Any = None

    async def setup(self) -> None:
        from aiokafka import AIOKafkaProducer  # type: ignore

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.config["bootstrap_servers"],
            client_id=self.config.get("client_id", "camera_dash"),
        )
        await self._producer.start()

    async def teardown(self) -> None:
        if self._producer is not None:
            import contextlib
            with contextlib.suppress(Exception):  # pragma: no cover
                await self._producer.stop()

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        topic = self.config["topic"]
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue
            try:
                await self._producer.send_and_wait(
                    topic, json.dumps(_to_json(payload), default=str).encode())
            except Exception:
                log.exception("kafka send failed")
