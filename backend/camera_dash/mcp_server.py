"""MCP server for camera_dash — exposes the pipeline/camera REST API as tools.

Talks to a running camera_dash backend over HTTP (default ``http://localhost:8001``,
override with ``CAMERA_DASH_API`` env var). This way the MCP server is decoupled
from the backend process and can be run from anywhere that can reach the API.

Run via::

    camera_dash mcp           # stdio transport (Claude Code / Claude Desktop)

Or directly::

    python -m camera_dash.mcp_server

Wire it into Claude Code's MCP config::

    {
      "mcpServers": {
        "camera_dash": {
          "command": "/path/to/.venv/bin/python",
          "args": ["-m", "camera_dash.mcp_server"],
          "env": { "CAMERA_DASH_API": "http://localhost:8001" }
        }
      }
    }
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API = os.environ.get("CAMERA_DASH_API", "http://localhost:8001").rstrip("/")
TIMEOUT = float(os.environ.get("CAMERA_DASH_API_TIMEOUT", "10"))

mcp = FastMCP("camera_dash")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=API, timeout=TIMEOUT)


# ----- Cameras -----


@mcp.tool()
async def list_cameras() -> list[dict[str, Any]]:
    """List all configured cameras with their status and WebRTC/HLS/RTSP URLs."""
    async with _client() as c:
        r = await c.get("/api/cameras")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def list_streams() -> list[dict[str, Any]]:
    """List derived streams (pipeline-produced video, e.g. annotated detections).
    Use alongside ``list_cameras`` to discover every available video tile.
    """
    async with _client() as c:
        r = await c.get("/api/streams")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def discover_cameras() -> dict[str, Any]:
    """Enumerate UVC devices the host sees (for help adding a new camera)."""
    async with _client() as c:
        r = await c.get("/api/cameras/discover")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def add_camera(
    id: str,
    kind: str,
    label: str = "",
    params: dict[str, Any] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Register a new camera. ``kind`` is ``uvc`` or ``flir_lepton``.
    ``params`` typically holds ``device_name`` / ``width`` / ``height`` / ``fps``.
    """
    body = {"id": id, "kind": kind, "label": label,
            "params": params or {}, "enabled": enabled}
    async with _client() as c:
        r = await c.post("/api/cameras", json=body)
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def remove_camera(id: str) -> dict[str, str]:
    """Stop and remove a camera by id."""
    async with _client() as c:
        r = await c.delete(f"/api/cameras/{id}")
        r.raise_for_status()
    return {"status": "removed", "id": id}


# ----- Pipelines -----


@mcp.tool()
async def list_pipelines() -> list[dict[str, Any]]:
    """List all stored pipeline definitions."""
    async with _client() as c:
        r = await c.get("/api/pipelines")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_pipeline(id: str) -> dict[str, Any]:
    """Fetch one pipeline definition by id."""
    async with _client() as c:
        r = await c.get(f"/api/pipelines/{id}")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def save_pipeline(
    id: str,
    name: str,
    definition: dict[str, Any],
    enabled: bool = False,
) -> dict[str, Any]:
    """Create or update a pipeline. ``definition`` is the graph JSON
    (``{id, name?, nodes: [...], edges: [...]}``). Validation runs server-side
    against the registered node catalog; an invalid graph returns 400.
    Setting ``enabled=True`` here only marks it; call ``start_pipeline`` to run.
    """
    body = {"id": id, "name": name, "definition": definition, "enabled": enabled}
    async with _client() as c:
        r = await c.put(f"/api/pipelines/{id}", json=body)
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def delete_pipeline(id: str) -> dict[str, str]:
    """Stop and delete a pipeline."""
    async with _client() as c:
        r = await c.delete(f"/api/pipelines/{id}")
        r.raise_for_status()
    return {"status": "deleted", "id": id}


@mcp.tool()
async def start_pipeline(id: str) -> dict[str, Any]:
    """Hot-start a pipeline by id."""
    async with _client() as c:
        r = await c.post(f"/api/pipelines/{id}/start")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def stop_pipeline(id: str) -> dict[str, Any]:
    """Hot-stop a pipeline by id."""
    async with _client() as c:
        r = await c.post(f"/api/pipelines/{id}/stop")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def pipeline_status() -> dict[str, Any]:
    """Runtime status: which pipelines are running, node counts, etc."""
    async with _client() as c:
        r = await c.get("/api/pipelines/status")
        r.raise_for_status()
        return r.json()


# ----- Catalog & events -----


@mcp.tool()
async def node_catalog() -> list[dict[str, Any]]:
    """Return the registered node catalog (type_id, ports, JSON schema, category).
    Use this to discover which nodes are available before composing a pipeline.
    """
    async with _client() as c:
        r = await c.get("/api/plugins")
        r.raise_for_status()
        return r.json().get("nodes", [])


@mcp.tool()
async def recent_events(
    limit: int = 50,
    pipeline_id: str | None = None,
    camera_id: str | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    """Recent events from the SQLite event log."""
    params: dict[str, Any] = {"limit": limit}
    if pipeline_id:
        params["pipeline_id"] = pipeline_id
    if camera_id:
        params["camera_id"] = camera_id
    if kind:
        params["kind"] = kind
    async with _client() as c:
        r = await c.get("/api/events", params=params)
        r.raise_for_status()
        return r.json()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
