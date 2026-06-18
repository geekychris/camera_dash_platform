"""Derived streams REST API — pipeline-produced video streams (e.g. annotated)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..streaming.mediamtx import hls_url, rtsp_url, webrtc_url

router = APIRouter()


@router.get("")
async def list_streams(request: Request) -> list[dict[str, Any]]:
    """List currently active derived streams (registered by ``sink.stream`` nodes)."""
    registry = request.app.state.derived_streams
    settings = request.app.state.settings
    out: list[dict[str, Any]] = []
    for s in registry.list():
        out.append({
            "id": s.id,
            "pipeline_id": s.pipeline_id,
            "node_id": s.node_id,
            "label": s.label,
            "source_camera_id": s.source_camera_id,
            "width": s.width,
            "height": s.height,
            "fps": s.fps,
            "kind": "derived",
            "urls": {
                "webrtc": webrtc_url(settings, s.id),
                "hls": hls_url(settings, s.id),
                "rtsp": rtsp_url(settings, s.id),
            },
        })
    return out
