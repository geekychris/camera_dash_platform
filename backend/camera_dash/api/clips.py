"""Clips REST API — list recorded clips and stream the mp4 files."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from ..storage import models
from ..storage.db import get_session

router = APIRouter()


@router.get("")
async def list_clips(
    camera_id: str | None = None,
    pipeline_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """List recorded clips, newest first. Filter by camera/pipeline if provided."""
    stmt = select(models.Clip).order_by(models.Clip.started_at.desc()).limit(limit)
    if camera_id:
        stmt = stmt.where(models.Clip.camera_id == camera_id)
    if pipeline_id:
        stmt = stmt.where(models.Clip.pipeline_id == pipeline_id)
    async with get_session() as s:
        rows = (await s.execute(stmt)).scalars().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        thumb_path = r.path.rsplit(".", 1)[0] + ".jpg" if r.path else None
        is_image = bool(r.path and r.path.lower().endswith((".jpg", ".jpeg", ".png")))
        out.append({
            "id": r.id,
            "camera_id": r.camera_id,
            "pipeline_id": r.pipeline_id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "trigger": r.trigger,
            "size_bytes": os.path.getsize(r.path) if r.path and os.path.exists(r.path) else 0,
            "exists": bool(r.path and os.path.exists(r.path)),
            "thumb": bool(thumb_path and os.path.exists(thumb_path)),
            "is_image": is_image,
        })
    return out


@router.get("/{clip_id}/thumb")
async def get_clip_thumb(clip_id: str) -> FileResponse:
    """Serve the JPG thumbnail for a clip."""
    async with get_session() as s:
        row = await s.get(models.Clip, clip_id)
    if row is None or not row.path:
        raise HTTPException(404, "clip not found")
    thumb = row.path.rsplit(".", 1)[0] + ".jpg"
    if not os.path.exists(thumb):
        raise HTTPException(404, "thumbnail not found")
    return FileResponse(thumb, media_type="image/jpeg")


@router.get("/{clip_id}/file")
async def get_clip_file(clip_id: str, request: Request) -> FileResponse:
    """Stream the mp4 file for a clip. Supports HTTP range requests via FileResponse."""
    async with get_session() as s:
        row = await s.get(models.Clip, clip_id)
    if row is None or not row.path or not os.path.exists(row.path):
        raise HTTPException(404, "clip not found")
    return FileResponse(row.path, media_type="video/mp4",
                        filename=os.path.basename(row.path))


@router.delete("/{clip_id}", status_code=204)
async def delete_clip(clip_id: str, request: Request) -> None:
    """Delete a clip's DB row and (best-effort) its file on disk."""
    async with get_session() as s:
        row = await s.get(models.Clip, clip_id)
        if row is None:
            raise HTTPException(404, "clip not found")
        path = row.path
        await s.delete(row)
        await s.commit()
    if path and os.path.exists(path):
        import contextlib
        with contextlib.suppress(OSError):
            os.remove(path)
