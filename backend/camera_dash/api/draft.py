"""AI pipeline composer — Claude generates a pipeline JSON from a NL prompt.

Pulls the registered node catalog so Claude knows exactly which nodes/ports exist,
asks it to return a single pipeline JSON, validates the result against the
catalog before returning.

Needs ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..pipeline.graph import Graph, GraphError
from ..plugins import describe_catalog

router = APIRouter()
log = logging.getLogger(__name__)


class DraftRequest(BaseModel):
    prompt: str
    pipeline_id: str | None = None
    cameras_hint: list[str] | None = None  # camera ids that should appear in source.camera nodes
    model: str | None = None


@router.post("")
async def draft_pipeline(req: DraftRequest, request: Request) -> dict[str, Any]:
    try:
        from anthropic import AsyncAnthropic  # type: ignore
    except ImportError as exc:
        raise HTTPException(500, "anthropic SDK not installed") from exc
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(400, "ANTHROPIC_API_KEY not set on the backend")

    catalog = request.app.state.catalog
    catalog_desc = describe_catalog(catalog)

    system = (
        "You design camera_dash pipelines. A pipeline is a JSON DAG of nodes from "
        "the provided catalog. Use ONLY nodes that appear in the catalog. Wire "
        "edges as `<from_node>.<from_port>` -> `<to_node>.<to_port>`. Each node "
        "needs `id` (unique), `type` (catalog type_id), and `config` matching the "
        "node's JSON schema. Return a single JSON object with keys: "
        "id, name, nodes, edges. NO explanation, NO markdown — just the JSON."
    )

    user_parts = [
        f"USER REQUEST:\n{req.prompt}\n\n",
        f"AVAILABLE CAMERAS (use these as camera_id values when needed): "
        f"{req.cameras_hint or '(unknown — leave a TODO placeholder)'}\n\n",
        f"CATALOG (one entry per node type):\n{json.dumps(catalog_desc, indent=2)}",
    ]
    client = AsyncAnthropic()
    model = req.model or "claude-sonnet-4-5"

    try:
        msg = await client.messages.create(
            model=model, max_tokens=4096, system=system,
            messages=[{"role": "user", "content": "".join(user_parts)}],
        )
    except Exception as exc:
        log.exception("anthropic call failed")
        raise HTTPException(502, f"anthropic call failed: {exc}") from exc

    raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
    # Tolerate ```json fences if Claude returns them anyway
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()
        if raw.startswith("json"):
            raw = raw[4:].lstrip()

    try:
        defn = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"model returned invalid JSON: {exc}\n\n{raw[:400]}") from exc

    if req.pipeline_id:
        defn["id"] = req.pipeline_id

    try:
        Graph.from_json(defn, catalog=catalog)
    except (GraphError, KeyError, ValueError) as exc:
        return {"definition": defn, "valid": False, "error": str(exc),
                "raw_model_output": raw[:2000]}
    return {"definition": defn, "valid": True}
