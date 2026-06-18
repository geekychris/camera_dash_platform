"""ntfy.sh sink — push to ntfy.sh topics. No account needed for the public server.

Self-hostable too; set ``base_url`` to your own ntfy instance.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ....pipeline.types import PortType
from ...node import Inbox, Node, Outbox, Port
from .telegram import _format

log = logging.getLogger(__name__)


class NtfySink(Node):
    TYPE_ID = "sink.ntfy"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["topic"],
        "properties": {
            "topic": {"type": "string", "description": "ntfy topic (e.g. 'home-cameras-alerts')"},
            "base_url": {"type": "string", "default": "https://ntfy.sh"},
            "priority": {"type": "integer", "enum": [1, 2, 3, 4, 5], "default": 4,
                          "description": "1=min .. 5=max (5 = urgent)"},
            "tags": {"type": "array", "items": {"type": "string"},
                      "default": ["camera", "alert"],
                      "description": "Emoji shortcodes or text tags"},
            "template": {"type": "string",
                          "default": "{kind} on {camera_id} — {summary}"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._client: httpx.AsyncClient | None = None

    async def setup(self) -> None:
        self._client = httpx.AsyncClient(timeout=10.0)

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        topic = self.config["topic"]
        base = self.config.get("base_url", "https://ntfy.sh").rstrip("/")
        url = f"{base}/{topic}"
        tags = ",".join(self.config.get("tags") or [])
        priority = str(int(self.config.get("priority", 4)))
        tmpl = self.config.get("template", "{kind} on {camera_id} — {summary}")
        assert self._client is not None
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue
            text = _format(tmpl, payload)
            try:
                await self._client.post(url, content=text.encode("utf-8"), headers={
                    "Priority": priority, "Tags": tags, "Title": "camera_dash",
                })
            except Exception:
                log.exception("ntfy post failed")
