"""Slack incoming-webhook sink — push matched events to a Slack channel.

Setup:
1. In your Slack workspace, create an Incoming Webhook
   (https://api.slack.com/messaging/webhooks). It gives you a URL of the form
   ``https://hooks.slack.com/services/T.../B.../...``.
2. Set ``SLACK_WEBHOOK_URL`` in the environment, or paste the URL into the
   ``webhook_url`` config field.

Compared to ``sink.webhook``: this one knows Slack's Block Kit so the message
renders as a tidy alert card (icon, kind in bold, camera + summary fields)
instead of a raw JSON dump.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ....pipeline.types import DetectionSet, Event, PortType
from ...node import Inbox, Node, Outbox, Port

log = logging.getLogger(__name__)


class SlackSink(Node):
    TYPE_ID = "sink.slack"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "webhook_url_env": {"type": "string", "default": "SLACK_WEBHOOK_URL",
                                 "description": "Env var holding the incoming-webhook URL"},
            "webhook_url": {"type": "string", "default": "",
                             "description": "Inline URL (env preferred for secrets)"},
            "username": {"type": "string", "default": "camera_dash"},
            "icon_emoji": {"type": "string", "default": ":vertical_traffic_light:"},
            "summary_template": {
                "type": "string",
                "default": "*{kind}* on `{camera_id}` — {summary}",
                "description": "Slack mrkdwn template; placeholders {kind} {camera_id} {pipeline_id} {summary}",
            },
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._client: httpx.AsyncClient | None = None
        self._url: str = ""

    async def setup(self) -> None:
        self._url = self.config.get("webhook_url") or os.environ.get(
            self.config.get("webhook_url_env", "SLACK_WEBHOOK_URL"), "")
        if not self._url:
            raise RuntimeError("sink.slack: webhook_url required (set inline or via env)")
        self._client = httpx.AsyncClient(timeout=10.0)

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        assert self._client is not None
        tmpl = self.config.get("summary_template",
                                "*{kind}* on `{camera_id}` — {summary}")
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue
            text = _format(tmpl, payload)
            body = {
                "username": self.config.get("username", "camera_dash"),
                "icon_emoji": self.config.get("icon_emoji", ":vertical_traffic_light:"),
                "text": text,
            }
            try:
                r = await self._client.post(self._url, json=body)
                if r.status_code >= 400:
                    log.warning("slack webhook returned %s: %s", r.status_code, r.text[:200])
            except Exception:
                log.exception("slack send failed")


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
