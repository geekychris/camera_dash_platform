"""Pipelines REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..examples_loader import substitute_placeholders
from ..pipeline.graph import Graph, GraphError
from ..storage import models
from ..storage.db import get_session

router = APIRouter()


class PipelineIn(BaseModel):
    id: str
    name: str = ""
    definition: dict[str, Any]
    enabled: bool = False


class PipelineOut(BaseModel):
    id: str
    name: str
    definition: dict[str, Any]
    enabled: bool


def _row_out(row: models.Pipeline) -> PipelineOut:
    return PipelineOut(id=row.id, name=row.name, definition=row.definition, enabled=row.enabled)


@router.get("", response_model=list[PipelineOut])
async def list_pipelines() -> list[PipelineOut]:
    async with get_session() as s:
        rows = (await s.execute(models.Pipeline.select_all())).scalars().all()
    return [_row_out(r) for r in rows]


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    return engine.status()


@router.get("/{pid}", response_model=PipelineOut)
async def get_pipeline(pid: str) -> PipelineOut:
    async with get_session() as s:
        row = await s.get(models.Pipeline, pid)
    if row is None:
        raise HTTPException(404, "pipeline not found")
    return _row_out(row)


@router.put("/{pid}", response_model=PipelineOut)
async def upsert_pipeline(pid: str, payload: PipelineIn, request: Request) -> PipelineOut:
    if pid != payload.id:
        raise HTTPException(400, "URL id != body id")
    catalog = request.app.state.catalog
    engine = request.app.state.engine
    try:
        graph = Graph.from_json(payload.definition, catalog=catalog)
    except (GraphError, KeyError, ValueError) as exc:
        raise HTTPException(400, f"invalid graph: {exc}") from exc

    # Was it running with the old definition? If so we restart it with the
    # new one after persisting — otherwise the editor's "Save" silently
    # leaves the in-memory engine on the stale graph and the dashboard's
    # output doesn't reflect the user's edits until they manually Stop+Start.
    was_running = pid in engine.status()

    async with get_session() as s:
        row = await models.Pipeline.upsert(s, pid, payload.name or pid,
                                           payload.definition, payload.enabled)
        await s.commit()
        await s.refresh(row)

    if was_running:
        # start_pipeline already stops the previous run, so a single call is
        # enough — and it leaves the camera/event/streaming wiring intact.
        await engine.start_pipeline(graph)
        # Reflect the runtime state in the persisted enabled flag.
        async with get_session() as s:
            row = await s.get(models.Pipeline, pid)
            if row is not None:
                row.enabled = True
                await s.commit()
                await s.refresh(row)
    return _row_out(row)


@router.post("", response_model=PipelineOut, status_code=201)
async def create_pipeline(payload: PipelineIn, request: Request) -> PipelineOut:
    return await upsert_pipeline(payload.id, payload, request)


@router.delete("/{pid}", status_code=204)
async def delete_pipeline(pid: str, request: Request) -> None:
    engine = request.app.state.engine
    await engine.stop_pipeline(pid)
    async with get_session() as s:
        await models.Pipeline.delete(s, pid)
        await s.commit()


@router.post("/{pid}/start", response_model=PipelineOut)
async def start_pipeline(pid: str, request: Request) -> PipelineOut:
    engine = request.app.state.engine
    catalog = request.app.state.catalog
    async with get_session() as s:
        row = await s.get(models.Pipeline, pid)
        if row is None:
            raise HTTPException(404, "pipeline not found")
        graph = Graph.from_json(row.definition, catalog=catalog)
        row.enabled = True
        await s.commit()
        await s.refresh(row)
    await engine.start_pipeline(graph)
    return _row_out(row)


class CloneReq(BaseModel):
    new_id: str
    name: str | None = None
    camera_map: dict[str, str] | None = None  # source camera_id -> replacement
    enabled: bool = False


def _source_camera_ids(definition: dict[str, Any]) -> list[str]:
    """Collect the distinct camera_id values referenced by source.* nodes."""
    seen: list[str] = []
    for n in definition.get("nodes", []):
        if not str(n.get("type", "")).startswith("source."):
            continue
        cid = (n.get("config") or {}).get("camera_id")
        if isinstance(cid, str) and cid not in seen:
            seen.append(cid)
    return seen


@router.post("/{pid}/clone", response_model=PipelineOut, status_code=201)
async def clone_pipeline(pid: str, req: CloneReq, request: Request) -> PipelineOut:
    """Clone an existing pipeline under ``new_id``, optionally rewiring camera_ids.

    The ``camera_map`` substitutes any node whose ``config.camera_id`` matches
    a key. For typical single-source pipelines the caller passes a one-entry
    map (e.g. ``{"laptop": "cam_new"}``); multi-source pipelines need one entry
    per source camera.
    """
    if req.new_id == pid:
        raise HTTPException(400, "new_id must differ from source pid")
    catalog = request.app.state.catalog
    async with get_session() as s:
        src = await s.get(models.Pipeline, pid)
        if src is None:
            raise HTTPException(404, "source pipeline not found")
        existing = await s.get(models.Pipeline, req.new_id)
        if existing is not None:
            raise HTTPException(409, f"pipeline {req.new_id} already exists")
        defn = substitute_placeholders(src.definition, req.camera_map or {})
        defn["id"] = req.new_id
        if req.name:
            defn["name"] = req.name
        try:
            Graph.from_json(defn, catalog=catalog)
        except (GraphError, KeyError, ValueError) as exc:
            raise HTTPException(400, f"invalid graph after substitution: {exc}") from exc
        name = req.name or (defn.get("name") if isinstance(defn.get("name"), str) else None) or req.new_id
        row = await models.Pipeline.upsert(s, req.new_id, name, defn, req.enabled)
        await s.commit()
        await s.refresh(row)
    if req.enabled:
        engine = request.app.state.engine
        await engine.start_pipeline(Graph.from_json(defn, catalog=catalog))
    return _row_out(row)


@router.get("/{pid}/source-cameras", response_model=list[str])
async def list_source_cameras(pid: str) -> list[str]:
    """Return the distinct camera_ids referenced by source.* nodes.

    Lets the UI offer an N-way camera_map for multi-source pipelines without
    needing to download and parse the whole definition.
    """
    async with get_session() as s:
        row = await s.get(models.Pipeline, pid)
    if row is None:
        raise HTTPException(404, "pipeline not found")
    return _source_camera_ids(row.definition)


@router.post("/{pid}/stop", response_model=PipelineOut)
async def stop_pipeline(pid: str, request: Request) -> PipelineOut:
    engine = request.app.state.engine
    await engine.stop_pipeline(pid)
    async with get_session() as s:
        row = await s.get(models.Pipeline, pid)
        if row is None:
            raise HTTPException(404, "pipeline not found")
        row.enabled = False
        await s.commit()
        await s.refresh(row)
    return _row_out(row)
