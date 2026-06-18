"""SMTP email sink — for daily summaries, "low-noise" alerts, etc."""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

from ....pipeline.types import PortType
from ...node import Inbox, Node, Outbox, Port
from .telegram import _format

log = logging.getLogger(__name__)


class EmailSink(Node):
    TYPE_ID = "sink.email"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["from_addr", "to_addrs"],
        "properties": {
            "host": {"type": "string", "default": "smtp.gmail.com"},
            "port": {"type": "integer", "default": 587},
            "use_tls": {"type": "boolean", "default": True},
            "user_env": {"type": "string", "default": "SMTP_USER"},
            "password_env": {"type": "string", "default": "SMTP_PASSWORD"},
            "from_addr": {"type": "string"},
            "to_addrs": {"type": "array", "items": {"type": "string"}},
            "subject_template": {"type": "string",
                                  "default": "[camera_dash] {kind} on {camera_id}"},
            "body_template": {"type": "string",
                               "default": "{kind} on {camera_id} — {summary}"},
        },
    }

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        host = self.config.get("host", "smtp.gmail.com")
        port = int(self.config.get("port", 587))
        use_tls = bool(self.config.get("use_tls", True))
        user = os.environ.get(self.config.get("user_env", "SMTP_USER"), "")
        pw = os.environ.get(self.config.get("password_env", "SMTP_PASSWORD"), "")
        from_addr = self.config["from_addr"]
        to_addrs = self.config["to_addrs"]
        subj_t = self.config.get("subject_template", "[camera_dash] {kind} on {camera_id}")
        body_t = self.config.get("body_template", "{kind} on {camera_id} — {summary}")
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue
            subject = _format(subj_t, payload)
            body = _format(body_t, payload)
            try:
                await asyncio.to_thread(_send, host, port, use_tls, user, pw,
                                         from_addr, to_addrs, subject, body)
            except Exception:
                log.exception("email send failed")


def _send(host: str, port: int, use_tls: bool, user: str, pw: str,
          from_addr: str, to_addrs: list[str], subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.set_content(body)
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port) as s:
        if use_tls:
            s.starttls(context=ctx)
        if user and pw:
            s.login(user, pw)
        s.send_message(msg)
