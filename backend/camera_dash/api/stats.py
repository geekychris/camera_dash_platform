"""Stats endpoint — per-camera fps, subscriber counts, pipeline status snapshot."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
async def stats(request: Request) -> dict[str, Any]:
    """Lightweight metrics — fps per camera, pipeline run state."""
    bus = request.app.state.frame_bus
    engine = request.app.state.engine
    camera_manager = request.app.state.camera_manager
    derived = request.app.state.derived_streams

    cams = camera_manager.list()
    sub_counts = bus.subscriber_counts()
    cameras_out = []
    for c in cams:
        cid = c["id"]
        cameras_out.append({
            "id": cid,
            "label": c.get("label") or cid,
            "kind": c["kind"],
            "running": c["running"],
            "fps": round(bus.fps(cid), 1),
            "subscribers": sub_counts.get(cid, 0),
        })

    derived_out = []
    for s in derived.list():
        derived_out.append({
            "id": s.id, "label": s.label, "fps": round(bus.fps(s.id), 1),
            "subscribers": sub_counts.get(s.id, 0),
        })

    return {
        "cameras": cameras_out,
        "derived": derived_out,
        "pipelines": engine.status(),
    }
