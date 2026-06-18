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
