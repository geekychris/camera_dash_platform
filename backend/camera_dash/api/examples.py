"""Examples API — list built-in pipeline examples + install them."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..examples_loader import load_examples, substitute_placeholders
from ..pipeline.graph import Graph, GraphError
from ..storage import models
from ..storage.db import get_session

router = APIRouter()


@router.get("")
async def list_examples(request: Request) -> list[dict[str, Any]]:
    """List all pipeline examples found under examples/pipelines/."""
    return load_examples(request.app.state.settings)


class InstallReq(BaseModel):
    camera_map: dict[str, str] | None = None  # placeholder -> real camera_id
    target_id: str | None = None              # override pipeline id (default: example id)
    enabled: bool = False                     # if true, also start the pipeline


@router.post("/{example_id}/install")
async def install_example(example_id: str, req: InstallReq, request: Request) -> dict[str, Any]:
    """Install an example as a real pipeline. Optional camera_map substitutes
    REPLACE_ME (or any other placeholder) camera_ids; target_id renames it."""
    examples = load_examples(request.app.state.settings)
    ex = next((e for e in examples if e["id"] == example_id), None)
    if ex is None:
        raise HTTPException(404, f"example {example_id} not found")
    defn = substitute_placeholders(ex["definition"], req.camera_map or {})
    pid = req.target_id or ex["id"]
    defn["id"] = pid

    # Validate against the catalog before persisting
    try:
        Graph.from_json(defn, catalog=request.app.state.catalog)
    except (GraphError, KeyError, ValueError) as exc:
        raise HTTPException(400, f"invalid graph after substitution: {exc}") from exc

    async with get_session() as s:
        row = await models.Pipeline.upsert(s, pid, defn.get("name", pid), defn, req.enabled)
        await s.commit()
        await s.refresh(row)

    if req.enabled:
        engine = request.app.state.engine
        await engine.start_pipeline(Graph.from_json(defn, catalog=request.app.state.catalog))

    return {"id": pid, "installed": True, "started": req.enabled,
            "name": row.name, "placeholders": ex["placeholders"],
            "mapped": req.camera_map or {}}
