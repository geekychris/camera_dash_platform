"""Pushover sink — paid-but-cheap mobile push (one-time $5)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ....pipeline.types import PortType
from ...node import Inbox, Node, Outbox, Port
from .telegram import _format

log = logging.getLogger(__name__)


class PushoverSink(Node):
    TYPE_ID = "sink.pushover"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "app_token_env": {"type": "string", "default": "PUSHOVER_APP_TOKEN"},
            "user_key_env": {"type": "string", "default": "PUSHOVER_USER_KEY"},
            "app_token": {"type": "string", "default": ""},
            "user_key": {"type": "string", "default": ""},
            "priority": {"type": "integer", "enum": [-2, -1, 0, 1, 2], "default": 0,
                          "description": "Pushover priority (2 = emergency, requires ack)"},
            "title": {"type": "string", "default": "camera_dash"},
            "template": {"type": "string",
                          "default": "{kind} on {camera_id} — {summary}"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._client: httpx.AsyncClient | None = None
        self._token: str = ""
        self._user: str = ""

    async def setup(self) -> None:
        self._token = self.config.get("app_token") or os.environ.get(
            self.config.get("app_token_env", "PUSHOVER_APP_TOKEN"), "")
        self._user = self.config.get("user_key") or os.environ.get(
            self.config.get("user_key_env", "PUSHOVER_USER_KEY"), "")
        if not self._token or not self._user:
            raise RuntimeError("sink.pushover: app_token + user_key required")
        self._client = httpx.AsyncClient(timeout=10.0)

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        tmpl = self.config.get("template", "{kind} on {camera_id} — {summary}")
        title = self.config.get("title", "camera_dash")
        priority = int(self.config.get("priority", 0))
        assert self._client is not None
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue
            try:
                await self._client.post("https://api.pushover.net/1/messages.json", data={
                    "token": self._token, "user": self._user,
                    "title": title, "priority": priority,
                    "message": _format(tmpl, payload),
                })
            except Exception:
                log.exception("pushover send failed")
