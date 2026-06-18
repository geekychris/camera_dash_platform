"""Telegram bot sink — push messages to a chat. Free, mobile-reachable.

Setup:
1. Talk to @BotFather, create a bot, get the bot token.
2. Send any message to your bot, then visit
   ``https://api.telegram.org/bot<TOKEN>/getUpdates`` to find your chat id.
3. Set those as ``bot_token`` + ``chat_id`` in this node's config (or env vars).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ....pipeline.types import DetectionSet, Event, PortType
from ...node import Inbox, Node, Outbox, Port

log = logging.getLogger(__name__)


class TelegramSink(Node):
    TYPE_ID = "sink.telegram"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "bot_token_env": {"type": "string", "default": "TELEGRAM_BOT_TOKEN"},
            "chat_id_env": {"type": "string", "default": "TELEGRAM_CHAT_ID"},
            "bot_token": {"type": "string", "default": "", "description": "Inline token (use env preferred)"},
            "chat_id": {"type": "string", "default": ""},
            "template": {"type": "string",
                          "default": "🚨 *{kind}* on `{camera_id}` — {summary}",
                          "description": "Markdown template; placeholders {kind} {camera_id} {summary} {pipeline_id}"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._client: httpx.AsyncClient | None = None
        self._token: str = ""
        self._chat: str = ""

    async def setup(self) -> None:
        self._token = self.config.get("bot_token") or os.environ.get(
            self.config.get("bot_token_env", "TELEGRAM_BOT_TOKEN"), "")
        self._chat = self.config.get("chat_id") or os.environ.get(
            self.config.get("chat_id_env", "TELEGRAM_CHAT_ID"), "")
        if not self._token or not self._chat:
            raise RuntimeError("sink.telegram: bot_token + chat_id required")
        self._client = httpx.AsyncClient(timeout=10.0)

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        tmpl = self.config.get("template",
                                "🚨 *{kind}* on `{camera_id}` — {summary}")
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
                await self._client.post(url, json={
                    "chat_id": self._chat, "text": text, "parse_mode": "Markdown",
                })
            except Exception:
                log.exception("telegram send failed")


def _format(tmpl: str, payload: Any) -> str:
    if isinstance(payload, Event):
        return tmpl.format(kind=payload.kind, camera_id=payload.camera_id or "?",
                            pipeline_id=payload.pipeline_id,
                            summary=_summary(payload.payload))
    if isinstance(payload, DetectionSet):
        labels = ", ".join(sorted({d.label for d in payload.detections}))
        return tmpl.format(kind="detection", camera_id=payload.camera_id,
                            pipeline_id="", summary=f"{len(payload.detections)} obj ({labels})")
    return repr(payload)


def _summary(p: dict[str, Any]) -> str:
    if "description" in p:
        return str(p["description"])
    if "labels" in p:
        return f"n={p.get('count', 0)} {p.get('labels', [])}"
    return ", ".join(f"{k}={v}" for k, v in p.items() if k not in ("polygon", "detections"))
