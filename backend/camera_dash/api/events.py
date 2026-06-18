"""Events API — SSE live tail + historical query."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from ..storage import models
from ..storage.db import get_session

router = APIRouter()


@router.get("/stream")
async def stream(request: Request) -> EventSourceResponse:
    """Server-Sent Events: live pipeline events as they fire."""
    bus = request.app.state.event_bus

    async def gen():
        q = await bus.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                except TimeoutError:
                    yield {"event": "ping", "data": ""}
                    continue
                yield {"event": "event", "data": json.dumps({
                    "pipeline_id": evt.pipeline_id,
                    "node_id": evt.node_id,
                    "camera_id": evt.camera_id,
                    "timestamp_ns": evt.timestamp_ns,
                    "kind": evt.kind,
                    "payload": evt.payload,
                }, default=str)}
        finally:
            await bus.unsubscribe(q)

    return EventSourceResponse(gen())


_LIMIT = Query(100, ge=1, le=1000)


@router.get("")
async def list_events(
    pipeline_id: str | None = None,
    camera_id: str | None = None,
    kind: str | None = None,
    since: datetime | None = None,
    limit: int = _LIMIT,
) -> list[dict[str, Any]]:
    stmt = select(models.Event).order_by(models.Event.timestamp.desc()).limit(limit)
    if pipeline_id:
        stmt = stmt.where(models.Event.pipeline_id == pipeline_id)
    if camera_id:
        stmt = stmt.where(models.Event.camera_id == camera_id)
    if kind:
        stmt = stmt.where(models.Event.kind == kind)
    if since:
        stmt = stmt.where(models.Event.timestamp >= since)
    async with get_session() as s:
        rows = (await s.execute(stmt)).scalars().all()
    return [{
        "id": r.id, "pipeline_id": r.pipeline_id, "node_id": r.node_id,
        "camera_id": r.camera_id, "timestamp": r.timestamp.isoformat(),
        "kind": r.kind, "payload": r.payload,
    } for r in rows]
