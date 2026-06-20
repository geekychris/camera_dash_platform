"""Web Push notifications API + an EventBus consumer that dispatches them.

The browser dashboard (service-worker.js) subscribes via
``POST /api/notifications/subscribe`` with the standard PushSubscription
JSON. Subscriptions are persisted in SQLite — they survive backend
restarts so a phone that subscribed yesterday still receives alerts today.

Two ways events get pushed:

1. **Subscribe to all events of a given kind** — when the EventBus emits
   an event whose ``kind`` is in the subscription's ``kinds`` filter (or
   the filter is empty), every subscription with that filter gets a push.
2. **Direct send** via ``POST /api/notifications/send`` with the same
   ``title / body / url / tag`` shape the service-worker handles. Useful
   for testing the round-trip or wiring a `sink.webhook` against it.

VAPID setup:
   Generate keys once with ``python -m camera_dash.cli vapid``. Set
   ``CAMERA_DASH_VAPID_PUBLIC_KEY`` + ``CAMERA_DASH_VAPID_PRIVATE_KEY`` +
   ``CAMERA_DASH_VAPID_CLAIMS_SUB`` (e.g. ``mailto:admin@hitorro.com``)
   in the environment. The /api/notifications/vapid endpoint returns the
   public key so the browser can subscribe with it.

This module imports the ``pywebpush`` library lazily — if it isn't
installed the endpoints return clear errors but the rest of the platform
keeps working.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


class PushSubscribePayload(BaseModel):
    subscription: dict[str, Any]   # Browser's PushSubscription JSON
    kinds: list[str] = []          # Event kinds to receive; empty = all


class PushSendPayload(BaseModel):
    title: str
    body: str = ""
    url: str = "/dashboard"
    tag: str = "default"
    icon: str | None = None
    kinds: list[str] | None = None  # Only deliver to subs matching these


@router.get("/vapid")
async def vapid_public_key() -> dict[str, str | None]:
    """Returns the VAPID public key so the dashboard can subscribe."""
    return {"publicKey": os.environ.get("CAMERA_DASH_VAPID_PUBLIC_KEY") or None}


@router.post("/subscribe")
async def subscribe(payload: PushSubscribePayload, request: Request) -> dict[str, Any]:
    store = request.app.state.notifications
    sub_id = await store.add(payload.subscription, payload.kinds)
    log.info("push subscription registered: id=%s kinds=%s", sub_id, payload.kinds or "ALL")
    return {"id": sub_id, "kinds": payload.kinds}


@router.delete("/subscribe/{sub_id}", status_code=204)
async def unsubscribe(sub_id: str, request: Request) -> None:
    store = request.app.state.notifications
    await store.remove(sub_id)


@router.post("/send")
async def send_test(payload: PushSendPayload, request: Request) -> dict[str, Any]:
    store = request.app.state.notifications
    sent = await store.dispatch({
        "title": payload.title,
        "body": payload.body,
        "url": payload.url,
        "tag": payload.tag,
        "icon": payload.icon,
    }, kinds=payload.kinds)
    return {"sent": sent}


# ----------------------------------------------------------------------
# Persistence + dispatch
# ----------------------------------------------------------------------


class NotificationStore:
    """In-memory + SQLite-backed registry of push subscriptions.

    A handful of subscriptions per user is the typical workload — we keep
    them in memory after load and lazy-write back to SQLite. Each entry is
    keyed by a short id so the client can later un-subscribe by id.
    """

    def __init__(self) -> None:
        self._subs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        from ..storage import models
        from ..storage.db import get_session

        async with get_session() as s:
            rows = (await s.execute(models.NotificationSubscription.select_all())).scalars().all()
        for r in rows:
            self._subs[r.id] = {
                "subscription": json.loads(r.subscription_json),
                "kinds": json.loads(r.kinds_json or "[]"),
            }
        log.info("loaded %d push subscriptions", len(self._subs))

    async def add(self, subscription: dict[str, Any], kinds: list[str]) -> str:
        from ..storage import models
        from ..storage.db import get_session

        # Use the subscription endpoint as a stable id so re-subscribing from
        # the same browser doesn't pile up duplicates.
        endpoint = subscription.get("endpoint", "")
        sub_id = _short_id(endpoint) if endpoint else _short_id(json.dumps(subscription, sort_keys=True))
        async with self._lock:
            self._subs[sub_id] = {"subscription": subscription, "kinds": list(kinds or [])}
            async with get_session() as s:
                await models.NotificationSubscription.upsert(
                    s, sub_id, json.dumps(subscription), json.dumps(list(kinds or [])),
                )
                await s.commit()
        return sub_id

    async def remove(self, sub_id: str) -> None:
        from ..storage import models
        from ..storage.db import get_session

        async with self._lock:
            self._subs.pop(sub_id, None)
            async with get_session() as s:
                await models.NotificationSubscription.delete(s, sub_id)
                await s.commit()

    async def dispatch(self, payload: dict[str, Any], kinds: list[str] | None = None) -> int:
        """Push to every matching subscription. Returns the count actually sent."""
        try:
            from pywebpush import WebPushException, webpush  # type: ignore
        except ImportError:
            log.warning("pywebpush not installed; push dispatch is a no-op")
            return 0

        priv = os.environ.get("CAMERA_DASH_VAPID_PRIVATE_KEY")
        sub_claim = os.environ.get("CAMERA_DASH_VAPID_CLAIMS_SUB", "mailto:admin@example.com")
        if not priv:
            log.warning("CAMERA_DASH_VAPID_PRIVATE_KEY unset; push dispatch skipped")
            return 0

        targets: list[tuple[str, dict[str, Any]]] = []
        async with self._lock:
            for sub_id, entry in self._subs.items():
                want = entry.get("kinds") or []
                if kinds and want and not (set(want) & set(kinds)):
                    continue
                targets.append((sub_id, entry["subscription"]))
        body = json.dumps(payload)

        def _push_one(sub_id: str, sub: dict[str, Any]) -> bool:
            try:
                webpush(
                    subscription_info=sub,
                    data=body,
                    vapid_private_key=priv,
                    vapid_claims={"sub": sub_claim},
                )
                return True
            except WebPushException as exc:  # pragma: no cover - network
                log.info("push to %s failed: %s", sub_id, exc)
                # 410/404 = subscription gone, prune so we don't keep retrying.
                if exc.response is not None and exc.response.status_code in (404, 410):
                    asyncio.create_task(self.remove(sub_id))
                return False
            except Exception:  # pragma: no cover - network
                log.exception("push failed unexpectedly")
                return False

        results = await asyncio.gather(
            *(asyncio.to_thread(_push_one, sid, sub) for sid, sub in targets),
            return_exceptions=False,
        )
        return sum(1 for r in results if r)


def _short_id(seed: str) -> str:
    import hashlib

    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
