"""Broadcast endpoints — read-only HTTP surfaces for in-platform broadcast nodes.

Currently:
* ``GET /api/broadcast/snapshot``                  — list registered snapshots
* ``GET /api/broadcast/snapshot/{stream_id}.jpg``  — latest JPEG for a snapshot

``stream_id`` may contain ``/`` (default form is ``<pipeline>/<node>``) so we
match the trailing ``.jpg`` with a path converter.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter()


@router.get("/snapshot")
async def list_snapshots(request: Request) -> list[dict]:
    reg = request.app.state.snapshots
    out = []
    for e in reg.list():
        out.append({
            "id": e.id, "pipeline_id": e.pipeline_id, "node_id": e.node_id,
            "label": e.label, "width": e.width, "height": e.height,
            "updated_at": e.updated_at,
            "url": f"/api/broadcast/snapshot/{e.id}.jpg",
        })
    return out


@router.get("/snapshot/{stream_id:path}.jpg")
async def get_snapshot(stream_id: str, request: Request) -> Response:
    reg = request.app.state.snapshots
    entry = reg.get(stream_id)
    if entry is None:
        raise HTTPException(404, f"snapshot {stream_id!r} not registered")
    # ``Last-Modified`` so curl --time-cond and conditional GETs work; embedders
    # like Grafana use this to skip re-fetches when the image hasn't updated.
    return Response(
        content=entry.jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache", "X-Updated-At": str(entry.updated_at)},
    )
