"""FastAPI application — boots capture, pipelines, and exposes the REST API."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import cameras as api_cameras
from .api import clips as api_clips
from .api import draft as api_draft
from .api import events as api_events
from .api import examples as api_examples
from .api import pipelines as api_pipelines
from .api import plugins as api_plugins
from .api import radiometric as api_radiometric
from .api import snapshots as api_snapshots
from .api import stats as api_stats
from .api import streams as api_streams
from .api import templates as api_templates
from .cameras.manager import CameraManager
from .pipeline.engine import PipelineEngine
from .plugins import load_catalog
from .recording.ring_buffer import RingBufferManager
from .settings import Settings
from .storage.db import init_db
from .streaming.event_bus import EventBus
from .streaming.frame_bus import FrameBus
from .streaming.gst import StreamingManager
from .streaming.registry import DerivedStreamRegistry


def _configure_logging() -> None:
    """Route ``camera_dash.*`` loggers to stderr; uvicorn only configures its own.

    Without this the ConsoleSink (and our camera/engine.log calls) disappear.
    """
    root = logging.getLogger("camera_dash")
    if root.handlers:
        return  # already configured (e.g. by tests)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root.propagate = False


_configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = os.environ.get("CAMERA_DASH_CONFIG")
    settings = Settings.from_yaml(cfg) if cfg else Settings()
    catalog = load_catalog()

    await init_db(settings.storage.dsn)

    frame_bus = FrameBus()
    event_bus = EventBus()
    derived_streams = DerivedStreamRegistry()
    camera_manager = CameraManager(settings=settings, frame_bus=frame_bus)
    streaming = StreamingManager(settings=settings, frame_bus=frame_bus)
    ring_buffers = RingBufferManager(settings=settings, clips_dir=settings.storage.clips_dir)
    engine = PipelineEngine(settings=settings, catalog=catalog, frame_bus=frame_bus,
                            camera_manager=camera_manager, event_bus=event_bus,
                            streaming=streaming, derived_streams=derived_streams,
                            ring_buffers=ring_buffers)

    app.state.settings = settings
    app.state.catalog = catalog
    app.state.frame_bus = frame_bus
    app.state.event_bus = event_bus
    app.state.derived_streams = derived_streams
    app.state.camera_manager = camera_manager
    app.state.streaming = streaming
    app.state.ring_buffers = ring_buffers
    app.state.engine = engine

    await camera_manager.start()
    # Auto-attach RTSP publishers for cameras that were persisted + auto-started.
    # Without this, the dashboard renders tiles but the MediaMTX paths are empty.
    for cam in camera_manager.list():
        if cam["running"]:
            p = cam["params"]
            await streaming.attach(
                cam["id"],
                int(p.get("width", 1280)),
                int(p.get("height", 720)),
                int(p.get("fps", 30)),
            )
    await engine.start()
    # Start persisted pipelines that are marked enabled
    from .pipeline.graph import Graph
    from .storage import models
    from .storage.db import get_session
    async with get_session() as s:
        rows = (await s.execute(models.Pipeline.select_all())).scalars().all()
    import contextlib
    for row in rows:
        if not row.enabled:
            continue
        with contextlib.suppress(Exception):  # pragma: no cover
            await engine.start_pipeline(Graph.from_json(row.definition, catalog=catalog))
    try:
        yield
    finally:
        await engine.stop()
        await streaming.stop_all()
        await ring_buffers.stop_all()
        await camera_manager.stop()


app = FastAPI(title="camera_dash", version="0.1.0", lifespan=lifespan)


def _configure_cors(app: FastAPI) -> None:
    origins = os.environ.get("CAMERA_DASH_CORS_ORIGINS", "http://localhost:5173").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


_configure_cors(app)

app.include_router(api_cameras.router, prefix="/api/cameras", tags=["cameras"])
app.include_router(api_pipelines.router, prefix="/api/pipelines", tags=["pipelines"])
app.include_router(api_events.router, prefix="/api/events", tags=["events"])
app.include_router(api_radiometric.router, prefix="/api/radiometric", tags=["radiometric"])
app.include_router(api_plugins.router, prefix="/api/plugins", tags=["plugins"])
app.include_router(api_streams.router, prefix="/api/streams", tags=["streams"])
app.include_router(api_clips.router, prefix="/api/clips", tags=["clips"])
app.include_router(api_stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(api_snapshots.router, prefix="/api/snapshots", tags=["snapshots"])
app.include_router(api_templates.router, prefix="/api/templates", tags=["pipelines"])
app.include_router(api_examples.router, prefix="/api/examples", tags=["pipelines"])
app.include_router(api_draft.router, prefix="/api/draft", tags=["pipelines"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
