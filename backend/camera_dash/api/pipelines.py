"""Pipelines REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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
    try:
        Graph.from_json(payload.definition, catalog=catalog)
    except (GraphError, KeyError, ValueError) as exc:
        raise HTTPException(400, f"invalid graph: {exc}") from exc
    async with get_session() as s:
        row = await models.Pipeline.upsert(s, pid, payload.name or pid,
                                           payload.definition, payload.enabled)
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
