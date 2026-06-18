"""Example external sink — posts a Slack message via incoming webhook.

Installing this package (``pip install -e examples/plugins/camera_dash_demo_sink``)
makes ``sink.slack_demo`` available in the camera_dash node catalog and in the
editor palette, with no changes to the core repo. This demonstrates the
entry-points based plugin mechanism.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

# Imports from the host application
from camera_dash.pipeline.node import Inbox, Node, Outbox, Port
from camera_dash.pipeline.types import DetectionSet, Event, PortType

log = logging.getLogger(__name__)


class SlackDemoSink(Node):
    TYPE_ID = "sink.slack_demo"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["webhook_url"],
        "properties": {
            "webhook_url": {"type": "string", "format": "uri"},
            "prefix": {"type": "string", "default": ":rotating_light:"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._client: httpx.AsyncClient | None = None

    async def setup(self) -> None:
        self._client = httpx.AsyncClient(timeout=5.0)

    async def teardown(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        url = self.config["webhook_url"]
        prefix = self.config.get("prefix", ":rotating_light:")
        assert self._client is not None
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue
            text = _format(payload, prefix)
            try:
                await self._client.post(url, json={"text": text})
            except Exception:
                log.exception("slack post failed")


def _format(payload: Any, prefix: str) -> str:
    if isinstance(payload, Event):
        return f"{prefix} *{payload.kind}* on `{payload.camera_id}` — `{payload.payload}`"
    if isinstance(payload, DetectionSet):
        labels = ", ".join(sorted({d.label for d in payload.detections}))
        return f"{prefix} detections on `{payload.camera_id}`: {labels}"
    return f"{prefix} {payload!r}"
