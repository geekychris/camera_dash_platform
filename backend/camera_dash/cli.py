"""``camera_dash`` CLI entry-point."""

from __future__ import annotations

from pathlib import Path

import click
import uvicorn

from .settings import Settings


@click.group()
def main() -> None:
    """camera_dash control CLI."""


@main.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=False,
    help="Path to a YAML deploy profile (e.g. configs/deploy.mac.yml).",
)
@click.option("--host", default=None)
@click.option("--port", type=int, default=None)
@click.option("--reload", is_flag=True, default=False)
def run(config: Path | None, host: str | None, port: int | None, reload: bool) -> None:
    """Run the backend server."""
    import os
    settings = Settings.from_yaml(config) if config else Settings()
    if config:
        # Propagate the chosen config to main.py's lifespan, which re-reads it.
        # Without this the lifespan uses defaults and the DB ends up CWD-relative.
        os.environ["CAMERA_DASH_CONFIG"] = str(Path(config).resolve())
    uvicorn.run(
        "camera_dash.main:app",
        host=host or settings.server.host,
        port=port or settings.server.port,
        reload=reload,
        factory=False,
        env_file=None,
    )


@main.command()
@click.argument("pipeline_json", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def validate(pipeline_json: Path) -> None:
    """Validate a pipeline JSON file against the node catalog without running it."""
    from .pipeline.graph import Graph
    from .plugins import load_catalog

    catalog = load_catalog()
    graph = Graph.from_json(pipeline_json.read_text(), catalog=catalog)
    click.echo(f"OK: {graph.id} — {len(graph.nodes)} nodes, {len(graph.edges)} edges")


@main.command("install-pipeline")
@click.argument("source", required=False)
@click.option("--all", "install_all", is_flag=True, default=False,
              help="Install every example under examples/pipelines/")
@click.option("--map", "mappings", multiple=True,
              help="Substitute camera ids: --map REPLACE_ME=front_door (repeatable)")
@click.option("--enable", is_flag=True, default=False,
              help="Also start the pipeline after installing")
@click.option("--api", default="http://localhost:8001",
              help="Backend URL (default http://localhost:8001)")
def install_pipeline(source: str | None, install_all: bool, mappings: tuple[str, ...],
                      enable: bool, api: str) -> None:
    """Install a pipeline into a running camera_dash backend.

    SOURCE can be:
      - a path to a pipeline JSON file  (camera_dash install-pipeline ./my.json)
      - an example id                   (camera_dash install-pipeline home_intrusion)
      - omitted with --all              (install every example)
    """
    import json as _json
    from pathlib import Path

    import httpx

    mapping: dict[str, str] = {}
    for m in mappings:
        if "=" not in m:
            raise click.ClickException(f"--map expects KEY=VALUE, got {m!r}")
        k, v = m.split("=", 1)
        mapping[k] = v

    if install_all and source:
        raise click.ClickException("--all and SOURCE are mutually exclusive")
    if not install_all and not source:
        raise click.ClickException("provide SOURCE (path or example id) or --all")

    with httpx.Client(base_url=api, timeout=30.0) as c:
        if install_all:
            examples = c.get("/api/examples").raise_for_status().json()
            click.echo(f"Installing {len(examples)} examples…")
            for ex in examples:
                _install_example(c, ex["id"], mapping, enable)
            return
        # SOURCE — try path first, fall back to example id
        p = Path(source) if source else None
        if p and p.is_file():
            defn = _json.loads(p.read_text())
            pid = defn["id"]
            for node in defn.get("nodes", []):
                cfg = node.get("config") or {}
                if cfg.get("camera_id") in mapping:
                    cfg["camera_id"] = mapping[cfg["camera_id"]]
            body = {"id": pid, "name": defn.get("name", pid),
                    "definition": defn, "enabled": enable}
            r = c.put(f"/api/pipelines/{pid}", json=body)
            r.raise_for_status()
            click.echo(f"  ✓ saved {pid}")
            if enable:
                c.post(f"/api/pipelines/{pid}/start").raise_for_status()
                click.echo(f"  ✓ started {pid}")
        else:
            _install_example(c, source, mapping, enable)


def _install_example(client: Any, example_id: str, mapping: dict[str, str],
                     enable: bool) -> None:
    import click  # local for import cycle safety

    body = {"camera_map": mapping, "enabled": enable}
    r = client.post(f"/api/examples/{example_id}/install", json=body)
    if r.status_code >= 400:
        click.echo(f"  ✗ {example_id}: {r.text}")
        return
    out = r.json()
    extra = " (started)" if out.get("started") else ""
    click.echo(f"  ✓ {out['id']}{extra}")


@main.command()
def mcp() -> None:
    """Run the MCP server (stdio transport).

    Requires ``pip install -e '.[mcp]'``. Talks to the camera_dash backend over
    HTTP at ``$CAMERA_DASH_API`` (default ``http://localhost:8001``).
    """
    try:
        from .mcp_server import main as run_mcp
    except ImportError as exc:
        raise click.ClickException(
            "MCP deps not installed; run: pip install -e '.[mcp]'"
        ) from exc
    run_mcp()


if __name__ == "__main__":
    main()
