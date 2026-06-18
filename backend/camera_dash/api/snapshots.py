"""Snapshot endpoint — grab a single JPEG from a camera, save to disk + DB."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import cv2
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..pipeline.types import Frame
from ..storage import models
from ..storage.db import get_session

router = APIRouter()


@router.post("/{camera_id}")
async def take_snapshot(camera_id: str, request: Request) -> dict[str, Any]:
    """Capture a snapshot from the camera's FrameBus and save as JPG.

    Records it in the clips table (so the same browser shows snapshots + clips).
    Snapshots have ``started_at == ended_at`` and a path ending in ``.jpg``.
    """
    bus = request.app.state.frame_bus
    settings = request.app.state.settings
    q = await bus.subscribe(camera_id, depth=2)
    try:
        frame: Frame = await asyncio.wait_for(q.get(), timeout=3.0)
    except TimeoutError as exc:
        raise HTTPException(404, f"no frames available from camera '{camera_id}'") from exc
    finally:
        await bus.unsubscribe(camera_id, q)

    snap_id = uuid.uuid4().hex
    out_dir = settings.storage.clips_dir
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{camera_id}_snap_{snap_id}.jpg")
    await asyncio.to_thread(cv2.imwrite, path, frame.data,
                              [cv2.IMWRITE_JPEG_QUALITY, 90])

    now = datetime.now(UTC)
    async with get_session() as s:
        s.add(models.Clip(
            id=snap_id, camera_id=camera_id, pipeline_id=None,
            started_at=now, ended_at=now, path=path,
            trigger={"kind": "snapshot", "manual": True},
        ))
        await s.commit()
    return {"id": snap_id, "camera_id": camera_id, "path": path,
            "width": frame.width, "height": frame.height}


@router.get("/{snap_id}/file")
async def get_snapshot_file(snap_id: str) -> FileResponse:
    async with get_session() as s:
        row = await s.get(models.Clip, snap_id)
    if row is None or not row.path or not os.path.exists(row.path):
        raise HTTPException(404, "snapshot not found")
    return FileResponse(row.path, media_type="image/jpeg")
