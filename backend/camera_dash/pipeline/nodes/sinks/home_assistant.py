"""Home Assistant sink — call an HA service on matched events.

Closes the loop between camera_dash's vision pipelines and your home
automation: motion at the front door → porch light on, fall detected →
voice announce, package delivered → notify your phone.

Two ways to use it:

1. **service** mode — call any HA service (the most flexible).
   Config: ``service: "light.turn_on"`` + ``service_data: {"entity_id": "light.porch"}``
   This is the same call you'd write in an HA automation's ``service:`` block.

2. **toggle** mode — convenience for the common "turn this thing on/off"
   case. Config: ``entity_id: "switch.recording_indicator"`` +
   ``action: "on"`` (or ``"off"`` / ``"toggle"``). Resolves to
   ``<domain>.turn_<on|off|toggle>`` automatically.

The sink ignores the event payload by default — it just triggers when an
event arrives on the input port. To pass detection labels or counts through
to HA, use ``template`` to interpolate event data into the service_data
(e.g. ``{"message": "Person detected with confidence {payload[score]:.2f}"}``).

Cooldown applies per-target so the same light isn't toggled 30 times a
second when a camera sees a stable person.

Setup:
1. In Home Assistant, Profile → Long-Lived Access Tokens → Create.
2. Set ``HOME_ASSISTANT_TOKEN`` + ``HOME_ASSISTANT_URL`` in the environment,
   or paste into ``token`` / ``url`` config fields.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from ....pipeline.types import Event, PortType
from ...node import Inbox, Node, Outbox, Port

log = logging.getLogger(__name__)


class HomeAssistantSink(Node):
    TYPE_ID = "sink.home_assistant"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "url_env": {"type": "string", "default": "HOME_ASSISTANT_URL",
                         "description": "Env var holding the HA base URL (e.g. http://homeassistant.local:8123)"},
            "url": {"type": "string", "default": "",
                     "description": "Inline base URL (env preferred)"},
            "token_env": {"type": "string", "default": "HOME_ASSISTANT_TOKEN",
                           "description": "Env var holding the Long-Lived Access Token"},
            "token": {"type": "string", "default": "",
                       "description": "Inline token (env preferred for secrets)"},
            # ----- Action mode -----
            "service": {"type": "string", "default": "",
                         "description": "Full HA service id (e.g. 'light.turn_on'). Wins over entity_id+action if both set."},
            "service_data": {"type": "object", "default": {},
                              "description": "Service data dict (e.g. {entity_id: light.porch, brightness: 255})"},
            "entity_id": {"type": "string", "default": "",
                           "description": "Convenience: target entity for the on/off/toggle action"},
            "action": {"type": "string", "default": "toggle",
                        "enum": ["on", "off", "toggle"],
                        "description": "What to do with entity_id when service is not set"},
            "cooldown_s": {"type": "number", "default": 5.0, "minimum": 0.0,
                            "description": "Per-target debounce — minimum seconds between calls to the same entity"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._client: httpx.AsyncClient | None = None
        self._base: str = ""
        self._token: str = ""
        # Last-fired timestamp per (service, target) so a steady stream of
        # detections doesn't hammer the same entity at frame rate.
        self._last_fired: dict[str, float] = {}

    async def setup(self) -> None:
        self._base = (
            self.config.get("url")
            or os.environ.get(self.config.get("url_env", "HOME_ASSISTANT_URL"), "")
        ).rstrip("/")
        self._token = self.config.get("token") or os.environ.get(
            self.config.get("token_env", "HOME_ASSISTANT_TOKEN"), "")
        if not self._base or not self._token:
            raise RuntimeError(
                "sink.home_assistant: url + token required (set inline or via env "
                "HOME_ASSISTANT_URL / HOME_ASSISTANT_TOKEN)")
        self._client = httpx.AsyncClient(
            timeout=5.0,
            headers={"Authorization": f"Bearer {self._token}",
                     "Content-Type": "application/json"},
        )

    async def teardown(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        assert self._client is not None
        cooldown = float(self.config.get("cooldown_s", 5.0))
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            payload = inputs.get("payload")
            if payload is None:
                continue

            service, data = self._resolve_call(payload)
            if not service:
                continue

            target_key = f"{service}:{data.get('entity_id', '')}"
            now = time.monotonic()
            if now - self._last_fired.get(target_key, 0.0) < cooldown:
                continue
            self._last_fired[target_key] = now

            # HA expects POST /api/services/<domain>/<action>
            domain, _, action = service.partition(".")
            url = f"{self._base}/api/services/{domain}/{action}"
            try:
                r = await self._client.post(url, json=data)
                if r.status_code >= 400:
                    log.warning("HA service call %s → %s: %s",
                                service, r.status_code, r.text[:200])
            except Exception:
                log.exception("HA service call failed: %s", service)

    def _resolve_call(self, payload: Any) -> tuple[str, dict[str, Any]]:
        """Pick the service + data to call for this event."""
        service = str(self.config.get("service") or "").strip()
        data = dict(self.config.get("service_data") or {})
        if service:
            return service, data
        entity = str(self.config.get("entity_id") or "").strip()
        if not entity:
            return "", {}
        domain = entity.split(".", 1)[0]
        action = str(self.config.get("action") or "toggle").lower()
        verb = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}.get(action, "toggle")
        return f"{domain}.{verb}", {"entity_id": entity, **data}
