"""HTTP webhook sink (POST JSON)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ....pipeline.types import PortType
from ...node import Inbox, Node, Outbox, Port
from .mqtt import _to_json

log = logging.getLogger(__name__)


class WebhookSink(Node):
    TYPE_ID = "sink.webhook"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "enum": ["POST", "PUT"], "default": "POST"},
            "headers": {"type": "object", "default": {}},
            "timeout_s": {"type": "number", "default": 5.0},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._client: httpx.AsyncClient | None = None

    async def setup(self) -> None:
        timeout = float(self.config.get("timeout_s", 5.0))
        self._client = httpx.AsyncClient(timeout=timeout,
                                         headers=self.config.get("headers") or {})

    async def teardown(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        url = self.config["url"]
        method = self.config.get("method", "POST")
        assert self._client is not None
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue
            try:
                await self._client.request(method, url, json=_to_json(payload))
            except Exception:
                log.exception("webhook %s %s failed", method, url)
