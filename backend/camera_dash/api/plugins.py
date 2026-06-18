"""Plugins API — exposes the node catalog so the editor can build its palette."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..plugins import describe_catalog

router = APIRouter()


@router.get("")
async def catalog(request: Request) -> dict[str, list]:
    cat = request.app.state.catalog
    return {"nodes": describe_catalog(cat)}
