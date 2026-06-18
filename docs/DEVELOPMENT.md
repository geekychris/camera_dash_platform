# camera_dash — Development guide

For contributors, plugin authors, and anyone forking the codebase.

## Repo layout

See [`ARCHITECTURE.md`](ARCHITECTURE.md#13-code-layout) for the full tree.

## Running tests

```bash
backend/.venv/bin/pytest -q
# 13 tests; no hardware or optional deps required
```

Tests live in `backend/tests/`. They cover:
- JSON round-trip for pipeline graphs + validation rules (cycle, type mismatch, unknown type)
- Engine end-to-end with synthetic source/sink (no real cameras)
- Condition nodes (`metadata_match` AST sandbox, `temperature_gate` radiometric correctness)
- Radiometric helpers (centi-Kelvin → Celsius, downsampling)

## Linting

```bash
backend/.venv/bin/ruff check backend/camera_dash
backend/.venv/bin/ruff check --fix backend/camera_dash
```

Config in `backend/pyproject.toml`: `select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]`. Ignored: line length, RUF012 (mutable class default for CONFIG_SCHEMA which is intentionally a plain dict).

## Frontend dev

```bash
cd frontend
npm run dev     # vite dev server with HMR at :5173
npm run build   # production bundle to dist/
npm run lint    # tsc -b (typecheck)
```

The frontend talks to the backend via the `/api` proxy in `vite.config.ts`.

## Writing a new node

Three files to touch:

1. **The node class** — somewhere under `backend/camera_dash/pipeline/nodes/<category>/`:
   ```python
   from typing import Any
   from ....pipeline.types import Frame, DetectionSet, PortType
   from ...node import Node, Port

   class MyNewNode(Node):
       TYPE_ID = "transform.mything"
       UI_CATEGORY = "transform"
       INPUTS = (Port("frame", PortType.FRAME),)
       OUTPUTS = (Port("frame", PortType.FRAME),)
       CONFIG_SCHEMA = {
           "type": "object",
           "properties": {
               "threshold": {"type": "number", "default": 0.5},
           },
       }

       async def process(self, **inputs: Any) -> dict[str, Any]:
           frame: Frame | None = inputs.get("frame")
           if frame is None:
               return {}
           # … do your thing …
           return {"frame": frame}
   ```

2. **Entry-point** in `backend/pyproject.toml`:
   ```toml
   [project.entry-points."camera_dash.nodes"]
   "transform.mything" = "camera_dash.pipeline.nodes.transforms.mything:MyNewNode"
   ```

3. **Reinstall** so pip picks up the new entry-point:
   ```bash
   backend/.venv/bin/pip install --force-reinstall --no-deps -e backend
   ```
   (Editable installs cache entry-points at install time — code changes are live, but adding an entry-point requires a reinstall.)

Restart the backend, hit `/api/plugins`, you should see the new node. It also auto-appears in the editor's palette.

### Implementation tips

- **For stateless one-in-one-out nodes**: override `process()`. The engine takes care of the loop.
- **For sources/sinks/throttles**: override `run()` for full control over the read/write loop.
- **Lazy-import heavy deps in `setup()`** rather than at module top — keeps backend startup fast and lets you mark the dep optional.
- **For long-running async work in a node**: use `asyncio.to_thread(...)` to keep the event loop happy. Don't block.
- **Frame data is a numpy array (BGR for color, GRAY16 for thermal)**. Copy if you mutate (`arr.copy()`), since the same frame may be visible to multiple subscribers.
- **Emit events to the broadcast bus** via `self.context.event_bus.publish_nowait(event)` if you want dashboards to see them in real time.

### Port types and queue semantics

| `PortType` | Queue depth | Drop policy | Used for |
|---|---|---|---|
| `FRAME` | 2 | drop-oldest | video |
| `DETECTIONS` | 4 | drop-oldest | bbox lists |
| `EVENT` | 256 | keep-all | alerts |
| `TRIGGER` | 64 | keep-all | recorder triggers |

`DETECTIONS → EVENT` is the one cross-type connection allowed (so condition outputs can drive sinks directly).

### Required vs optional ports

A `Port` with `required=True` (default): `Inbox.read_all()` blocks waiting for an item before each `process()` tick.

A `Port` with `required=False`: `read_all()` reads non-blocking; missing inputs come through as `None`. Useful for "frame + maybe detections" patterns (e.g. `transform.privacy_mask`).

## Writing an external plugin

A plugin lives in its own pip-installable package and uses entry-points to register nodes. The package needs:

```toml
# my_plugin/pyproject.toml
[project]
name = "camera_dash_my_plugin"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["httpx>=0.27"]

[project.entry-points."camera_dash.sinks"]
"sink.my_thing" = "camera_dash_my_plugin.my_thing:MyThingSink"
```

```python
# my_plugin/camera_dash_my_plugin/my_thing.py
from camera_dash.pipeline.node import Inbox, Node, Outbox, Port
from camera_dash.pipeline.types import PortType

class MyThingSink(Node):
    TYPE_ID = "sink.my_thing"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {"type": "object", "properties": {}}

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        while True:
            inputs = await inbox.read_all()
            if inputs is None: return
            # …
```

Install into the camera_dash venv: `pip install -e my_plugin/` → restart backend → node shows up.

See `examples/plugins/camera_dash_demo_sink/` for a working example (a fake Slack webhook).

## Writing a new camera kind

Subclass `Camera` (from `camera_dash.cameras.base`), implement `async def start()` and `async def stop()`. In `start()`, publish frames to `self.frame_bus.publish_nowait(self.id, frame)`. Register it in `cameras/manager.py`'s `_DRIVERS` dict.

There's no entry-point mechanism for camera drivers yet — they're hardcoded. PRs welcome.

## Adding a new tile type to the dashboard

1. Create `frontend/src/dashboard/MyTile.tsx` exporting a React component that takes whatever props it needs.
2. Add a new tile state slot to `Stored` in `Dashboard.tsx`:
   ```ts
   type Stored = {
     // ...
     myTiles: Record<string, StoredMyTile>;
   };
   ```
3. Wire up: add a button to the toolbar (`+ MyTile`), an `addMyTile()` function, a `removeMyTile()` function, render it in the canvas.

The pattern is the same as `LogTile` / `AlertTile` / `StatsTile` / `TimelineTile` — copy whichever is closest to what you need.

## Debugging

### Where are the logs?

- Backend: stderr from the python process. `./scripts/run.sh` redirects to `/tmp/camera_dash_backend.log`.
- MediaMTX: same, `/tmp/camera_dash_mediamtx.log`.
- Frontend (vite): `/tmp/camera_dash_frontend.log`.

Tail them:
```bash
./scripts/run.sh logs
# or
tail -F /tmp/camera_dash_*.log
```

### Live SSE event firehose

```bash
curl -N http://localhost:8001/api/events/stream
```

Useful when adding nodes that emit events — confirm they actually surface.

### Inspect the pipeline engine

```bash
curl -s http://localhost:8001/api/pipelines/status | python3 -m json.tool
```

Shows what's running and how many nodes are alive per pipeline.

### Inspect the node catalog

```bash
curl -s http://localhost:8001/api/plugins | python3 -m json.tool
```

Same data the editor's palette uses.

## Release / packaging

There's no release process yet. The Docker images in `docker-compose.yml` reference `camera_dash/backend:dev` / `camera_dash/frontend:dev` tags built locally.

For a real release you'd want to:
1. Pin all deps in `pyproject.toml` (currently uses lower bounds)
2. Pin npm deps in `package-lock.json` (we have one — `npm ci` instead of `npm install`)
3. Build multi-arch Docker images (arm64 for RPi + Apple Silicon, amd64 for x86 Linux)
4. Tag a git release; ship the Docker images to a registry.

## Common patterns to follow

- **Async-everywhere**. Even teardown returns coroutines. Don't do blocking work in handlers.
- **Bound queues with drop-oldest** for any "live" data type. Unbounded queues cause memory bloat and stalls.
- **One file per node**. Easier to grep; easier to remove. Even small ones get their own file.
- **JSON Schema for config**. Renders as a form in the editor; documents the node; validates pipeline JSON.
- **Tests don't need hardware**. Use the synthetic source pattern in `tests/test_pipeline_engine.py`.
