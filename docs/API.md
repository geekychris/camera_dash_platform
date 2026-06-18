# camera_dash — API Reference

Backend is FastAPI, so the canonical interactive reference is `http://localhost:8001/docs` (Swagger UI). This document is the readable summary.

All responses are JSON unless noted. The default port is **8001** (changed from 8000 because that was taken by another app of the developer's; configurable in `configs/deploy.*.yml`).

---

## Cameras

```
GET    /api/cameras              List configured cameras
GET    /api/cameras/discover     Enumerate UVC devices visible to GStreamer
POST   /api/cameras              Add a camera
DELETE /api/cameras/{id}         Stop + remove a camera
PATCH  /api/cameras/{id}         Rename (body: {"label": "..."})
```

**Add camera body:**
```json
{
  "id": "front_door",
  "kind": "rtsp",
  "label": "Front door",
  "params": { "url": "rtsp://user:pass@10.0.0.50/stream", "transport": "tcp" },
  "enabled": true
}
```

Camera kinds: `uvc`, `flir_lepton`, `rtsp`, `screen`, `oak`. See [USER_MANUAL.md](USER_MANUAL.md#cameras-tab) for per-kind params.

**Camera info response:**
```json
{
  "id": "front_door",
  "kind": "rtsp",
  "label": "Front door",
  "params": { ... },
  "running": true,
  "is_thermal": false,
  "urls": {
    "webrtc": "http://127.0.0.1:8889/camera/front_door/whep",
    "hls":    "http://127.0.0.1:8888/camera/front_door/index.m3u8",
    "rtsp":   "rtsp://127.0.0.1:8554/camera/front_door"
  }
}
```

---

## Streams (derived)

Streams produced by `sink.stream` nodes inside running pipelines.

```
GET /api/streams                 List derived streams
```

Response shape is similar to cameras (each has `urls.webrtc` etc.) plus `pipeline_id`, `node_id`, and `source_camera_id`.

---

## Pipelines

```
GET    /api/pipelines            List pipelines (id, name, enabled)
GET    /api/pipelines/{id}       Get one pipeline (with definition)
PUT    /api/pipelines/{id}       Create or update
POST   /api/pipelines            Same as PUT, just a different verb
DELETE /api/pipelines/{id}       Stop and delete
POST   /api/pipelines/{id}/start Hot-start
POST   /api/pipelines/{id}/stop  Hot-stop
GET    /api/pipelines/status     Runtime status (which pipelines are running)
```

**Pipeline body:**
```json
{
  "id": "intrusion",
  "name": "Intrusion alert",
  "enabled": false,
  "definition": {
    "id": "intrusion",
    "name": "Intrusion alert",
    "nodes": [
      { "id": "src",  "type": "source.camera", "config": { "camera_id": "front_door" } },
      { "id": "yolo", "type": "detector.yolo", "config": { "classes": ["person"] } },
      { "id": "log",  "type": "sink.console",  "config": { "prefix": "[intrusion] " } }
    ],
    "edges": [
      { "from": "src.frame",       "to": "yolo.frame" },
      { "from": "yolo.detections", "to": "log.payload" }
    ]
  }
}
```

PUT/POST validate the graph against the node catalog before persisting; invalid graphs return 400 with a precise error (unknown type, port mismatch, cycle, etc.).

---

## Pipeline templates

```
GET /api/templates               List built-in pipeline templates
```

Returns 4 templates: intrusion, zone_dwell, thermal_alarm, pet_door. Each has a `definition` you can take, replace `REPLACE_ME` camera ids, and PUT to `/api/pipelines/{id}`.

---

## AI pipeline composer

```
POST /api/draft                  Claude generates a pipeline from a NL prompt
```

**Body:**
```json
{
  "prompt": "When a person is detected, log to console and record a 30 second clip",
  "pipeline_id": "my_new_pipeline",
  "cameras_hint": ["laptop", "flir"]
}
```

**Response:**
```json
{
  "definition": { /* full pipeline JSON */ },
  "valid": true,
  "error": null
}
```

If validation fails the response includes `valid: false` and `raw_model_output` so you can debug. Requires `ANTHROPIC_API_KEY` env var on the backend.

---

## Plugins (node catalog)

```
GET /api/plugins                 The full node catalog (used by the editor palette)
```

Returns `{ "nodes": [ {type_id, category, inputs, outputs, config_schema, doc}, ... ] }`. Each node's `config_schema` is JSON Schema — render it as a form with rjsf or similar.

---

## Events

```
GET /api/events?...              Historical query (paginated)
GET /api/events/stream           Server-Sent Events (live tail)
```

**Query params:** `pipeline_id`, `camera_id`, `kind`, `since`, `limit` (default 100, max 1000).

**SSE payload:**
```
event: event
data: {"pipeline_id":"intrusion","node_id":"log","camera_id":"front_door","timestamp_ns":1781750582155497000,"kind":"console","payload":{...}}
```

A heartbeat `ping` event is sent every 15s when idle (to keep the connection alive).

---

## Radiometric WebSocket

```
WS /api/radiometric/{camera_id}   Per-frame 16-bit thermal matrix
```

Only meaningful for `flir_lepton` cameras. Binary frames in this format:

```
[uint16 LE: width]
[uint16 LE: height]
[uint16 LE × width × height: centi-Kelvin values]
```

Convert to Celsius: `(value / 100) - 273.15`. The matrix is downsampled to ≤320px max dim to keep bandwidth reasonable.

---

## Clips

```
GET    /api/clips                List clips (filter by camera/pipeline; default 100)
GET    /api/clips/{id}/file      Stream the mp4 (or jpg for snapshots) — supports HTTP range
GET    /api/clips/{id}/thumb     Serve the JPG thumbnail for an mp4 clip
DELETE /api/clips/{id}           Delete DB row + file
```

**Clip response shape:**
```json
{
  "id": "abc123",
  "camera_id": "front_door",
  "pipeline_id": "intrusion",
  "started_at": "2026-06-18T02:31:09.953979+00:00",
  "ended_at":   "2026-06-18T02:31:39.953979+00:00",
  "trigger":   { "node_id": "match", "kind": "metadata_match", "payload": {...} },
  "size_bytes": 1843218,
  "exists":    true,
  "thumb":     true,
  "is_image":  false
}
```

---

## Snapshots

```
POST /api/snapshots/{camera_id}  Capture current frame as JPEG
GET  /api/snapshots/{snap_id}/file  Serve the JPEG
```

Snapshots are persisted in the same `clips` table with `is_image: true`, so they show up in the clip browser alongside recordings.

---

## Stats

```
GET /api/stats                   Per-camera fps + pipeline status
```

```json
{
  "cameras": [
    { "id":"laptop", "label":"MBP", "kind":"uvc", "running":true, "fps":30.2, "subscribers":3 }
  ],
  "derived": [
    { "id":"derived/intrusion/stream", "label":"intrusion+boxes", "fps":24.1, "subscribers":1 }
  ],
  "pipelines": {
    "intrusion": { "id":"intrusion", "nodes":[...], "running":6 }
  }
}
```

Backed by an in-memory rolling window of frame-publish timestamps on the FrameBus.

---

## Health

```
GET /health                      Always returns 200 {"status":"ok"} when the app is up
```

---

# MCP server

Run via `camera_dash mcp` (stdio transport). Add to Claude Code / Claude Desktop:

```json
{
  "mcpServers": {
    "camera_dash": {
      "command": "/path/to/backend/.venv/bin/python",
      "args": ["-m", "camera_dash.mcp_server"],
      "env": { "CAMERA_DASH_API": "http://localhost:8001" }
    }
  }
}
```

Tools (each wraps a REST endpoint):

| Tool | Args | Wraps |
|---|---|---|
| `list_cameras` | — | `GET /api/cameras` |
| `discover_cameras` | — | `GET /api/cameras/discover` |
| `add_camera` | id, kind, label, params, enabled | `POST /api/cameras` |
| `remove_camera` | id | `DELETE /api/cameras/{id}` |
| `list_streams` | — | `GET /api/streams` |
| `list_pipelines` | — | `GET /api/pipelines` |
| `get_pipeline` | id | `GET /api/pipelines/{id}` |
| `save_pipeline` | id, name, definition, enabled | `PUT /api/pipelines/{id}` |
| `delete_pipeline` | id | `DELETE /api/pipelines/{id}` |
| `start_pipeline` | id | `POST /api/pipelines/{id}/start` |
| `stop_pipeline` | id | `POST /api/pipelines/{id}/stop` |
| `pipeline_status` | — | `GET /api/pipelines/status` |
| `node_catalog` | — | `GET /api/plugins` |
| `recent_events` | limit, pipeline_id, camera_id, kind | `GET /api/events` |

The MCP server hits the REST API over HTTP, so the backend must be running. Default `CAMERA_DASH_API` is `http://localhost:8001`.
