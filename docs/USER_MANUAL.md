# camera_dash — User Manual

A practical guide to using the platform. Assumes you've installed it (see [`INSTALLATION.md`](INSTALLATION.md)) and have the three services running:
- **MediaMTX** on ports 8554/8888/8889/9997
- **Backend** on http://localhost:8001
- **Frontend** on http://localhost:5173

Open `http://localhost:5173` in your browser.

---

## Tabs

The top nav has five tabs:

| Tab | What you do here |
|---|---|
| **Dashboard** | View live video, add log/alert/stats/timeline tiles, draw zones, take snapshots |
| **Pipelines** | Build / edit / start / stop processing pipelines (visual editor) |
| **Cameras** | Add or remove cameras, rename them |
| **Clips** | Browse recorded clips and snapshots; play, download, delete |
| **Events** | Live SSE feed + historical event query (developer view of the firehose) |

---

## Cameras tab

Five camera kinds are supported:

| Kind | Use case | Typical `params` |
|---|---|---|
| `uvc` | USB webcam / built-in camera | `device_name` (preferred) or `device_index`, `width`, `height`, `fps` |
| `flir_lepton` | PureThermal + Lepton 3/3.5 thermal core | `device_name: "PureThermal (fw:v1.0.0)"`, `fps: 9` |
| `rtsp` | Any IP camera (HikVision, Reolink, ONVIF) | `url: "rtsp://user:pass@host/stream"`, `transport: "tcp"` |
| `screen` | Capture your desktop as a virtual camera | `display_id: 0`, `fps: 15` (crop_x/y/w/h optional on Linux) |
| `oak` | Luxonis OAK-D / OAK-1 stereo camera | `mxid` (optional), `width: 1280`, `height: 720`, `fps: 30` |

### Adding a camera

1. **Cameras → "Discover UVC"** — lists USB devices the host sees.
2. Type an `id` (your choice, must be unique), pick a kind, enter the params, click **Add**.
3. The backend opens the device, attaches a streaming publisher, and the camera shows up on the Dashboard.

### Camera identification

USB device-index isn't stable across replugs. Use `device_name` whenever possible (matched against what GStreamer/AVFoundation reports). The discover button will show you the names.

### FLIR-specific notes

- The PureThermal ships in **AGC mode** out of the box (8-bit visual stretched to 16-bit). The temperature-on-hover overlay will show meaningless values until you switch the camera to **radiometric mode** using the [GroupGets PureThermal Lepton UVC Capture app](https://github.com/groupgets/purethermal1-uvc-capture). The mode persists across power cycles.
- Lepton 3.x runs at ~9 FPS; setting `fps` higher won't help.

---

## Dashboard

The dashboard is a free-positioning canvas of draggable, resizable tiles. There are 6 tile types:

| Tile type | What it shows | How to add |
|---|---|---|
| Camera tile | Live WebRTC video from a physical camera | Auto-added when you add a camera |
| Derived stream tile | Pipeline-produced video (e.g. with bounding boxes overlaid) | Auto-added when a `sink.stream` node starts publishing |
| **+ Log** | Terminal-style scrollback of pipeline events (SSE feed) | Toolbar button |
| **+ Alert** | Flashing/audible alerts filtered by pipeline + event kind | Toolbar button |
| **+ Stats** | Live fps / queue depths / pipeline status | Toolbar button |
| **+ Timeline** | Last 5min/15min/1h/6h of events as a colored stripe per pipeline | Toolbar button |

### Tile controls

- **Move:** drag the title bar
- **Resize:** drag any edge or any of the 4 corners
- **Zoom video:** scroll wheel over a camera tile (100%–800%)
- **Snapshot 📷:** captures a JPEG to the Clips tab
- **Polygon ▱:** opens an editor for drawing zone polygons (see below)
- **REC indicator:** flashes red on a camera tile when a clip-relevant event fires for it
- **Reset layout** (toolbar): clears all saved tile positions/configs

### Polygon editor (for `condition.zone`)

The `▱` button on a camera tile opens a modal:

1. Click **Freeze frame** to take a still you can draw on
2. Click points around the area you care about
3. Click **Copy coords** to copy the JSON polygon to your clipboard
4. Paste it into a `condition.zone` node's `polygon` config in the Pipelines tab

The polygon is in pixel coordinates matching the camera's native resolution.

### Log tile

- Subscribes to the live SSE event stream
- **⚙** opens a config panel with filters: `pipelineFilter` (exact pipeline id) and `kindFilter` (exact event kind like `zone_enter`, `temperature_gate`, etc.)
- **❚❚** pauses; **clear** wipes; **×** removes the tile

### Alert tile

Same as log tile but visually shouty:
- Title bar flashes red + animate-pulse when a matching event arrives
- Optional beep (browser may block autoplay until your first interaction)
- `kindFilter` supports comma-separated kinds (e.g. `zone_enter,temperature_gate`)

### Stats tile

Live, refreshed every 1 second:
- Per camera: kind, fps, subscriber count
- Per derived stream: label, fps, subscribers
- Per pipeline: running/total node count

### Timeline tile

A horizontal strip per pipeline showing event ticks color-coded by kind, over the last 5min / 15min / 1h / 6h. Hover for `kind · time · camera_id`.

### FLIR temp-on-hover

If a camera has `is_thermal: true`, mouseover anywhere on the tile shows the temperature at that pixel (in °C). This reads the raw radiometric matrix via the WebSocket at `/api/radiometric/{camera_id}`.

---

## Pipelines (visual editor)

Pipelines are JSON DAGs of typed nodes. Build them in the visual editor.

### Sidebar

- **+ New (blank)** — start an empty graph
- **✨ Draft with AI** — type a natural-language description; Claude generates a complete pipeline JSON (needs `ANTHROPIC_API_KEY` on the backend). The model gets your camera ids and the full node catalog.
- **📋 From template** — pick one of the 4 built-in templates:
  - `tpl_intrusion` — Person detected → record clip + ntfy.sh push
  - `tpl_zone_dwell` — Person in polygon zone for 10s → log + ntfy
  - `tpl_thermal_alarm` — FLIR hotspot → Claude describes the visible-spectrum frame + record
  - `tpl_pet_door` — Dog/cat detected → log (debounced)

  Templates with `"camera_id": "REPLACE_ME"` need you to fill in a real camera id before saving.

### Canvas

- Drag nodes from the palette (bottom-left) onto the canvas
- Click an output handle and drag to an input handle to wire an edge (typed; incompatible ports refuse to connect)
- Click a node to edit its config in the right panel (auto-generated from the node's JSON Schema)
- Top bar: rename, **Save**, **Start**, **Stop**

### Authoring without the editor

You can also write pipeline JSON by hand and POST it via the REST API:

```bash
curl -X PUT http://localhost:8001/api/pipelines/myrule \
  -H "content-type: application/json" -d @my_pipeline.json
curl -X POST http://localhost:8001/api/pipelines/myrule/start
```

See [`NODES.md`](NODES.md) for the full node reference and [`API.md`](API.md) for the REST surface.

---

## Clips browser

The `/clips` page is your NVR-style review surface.

- **Grid mode** (default) — thumbnails for each clip; snapshots show inline as JPEG, video clips show their thumbnail
- **List mode** — detailed table with sortable columns
- **Filters**: camera id, pipeline id
- Click a thumbnail to play; **Download** saves the mp4/jpg; **delete** removes both the DB row and the file
- Clips are made by `sink.recorder` nodes when their `trigger` input fires; thumbnails are auto-generated at write time

### Where clips live on disk

`./data/clips/<camera_id>_<uuid>.mp4` + `.jpg` (thumbnail)
For snapshots: `<camera_id>_snap_<uuid>.jpg`

The clips directory is resolved relative to the **config file's parent directory** (not CWD), so it's stable regardless of where you launch the backend from.

---

## Events tab

A developer-leaning view:
- **Live** pane: SSE-tailed events with no filters
- **Recent (DB)** pane: last 50 events from the SQLite log
- Use this to debug pipelines or watch the raw stream for anything

---

## Pipelines you'll commonly want

### "Tell me when there's a person, but not 100 times per minute"

```mermaid
flowchart LR
    src["source.camera<br/>(my_cam)"]
    yolo["detector.yolo<br/>classes: [person]"]
    trk["transform.tracker"]
    match["condition.metadata_match<br/>d.label == 'person'"]
    cool["condition.cooldown<br/>60s · per_camera"]
    rec["sink.recorder<br/>pre 5s · post 30s"]
    ntfy["sink.ntfy<br/>topic: my_alerts"]
    src --> yolo --> trk --> match -- match --> cool -- match --> rec
    cool -- match --> ntfy
```

### "Anything dwelling in this area at night"

```mermaid
flowchart LR
    src["source.camera<br/>(my_cam)"]
    yolo["detector.yolo<br/>classes: [person]"]
    trk["transform.tracker"]
    zone["condition.zone<br/>fire_on: dwell · 10s"]
    sched["condition.schedule<br/>21:00 → 06:00"]
    tg["sink.telegram"]
    src --> yolo --> trk --> zone -- match --> sched -- match --> tg
```

### "Describe what's happening in plain English when the thermal sensor alarms"

```mermaid
flowchart LR
    flir["source.camera<br/>(flir)"]
    rgb["source.camera<br/>(rgb)"]
    gate["condition.temperature_gate<br/>min 60°C"]
    vlm["detector.vision_llm<br/>prompt: 'Describe what is hot'"]
    log["sink.console"]
    rec["sink.recorder"]
    flir -- frame --> gate
    gate -- match --> vlm
    rgb -- frame --> vlm
    vlm -- event --> log
    gate -- match --> rec
```

---

## Notifications (mobile push)

Drop one of these sinks at the end of any condition chain:

| Sink | Config | Notes |
|---|---|---|
| `sink.ntfy` | `topic` | Free, no account. Install ntfy app, subscribe to your topic. |
| `sink.telegram` | `bot_token` + `chat_id` (or env vars) | Free. Make a bot via @BotFather. |
| `sink.pushover` | `app_token` + `user_key` | $5 one-time, supports emergency priority |
| `sink.email` | SMTP host/port + creds | For digests or low-noise alerts |

All four use the same `{kind} on {camera_id} — {summary}` template by default; override `template` in the node config.

---

## MCP integration (Claude Code, Claude Desktop)

camera_dash ships an MCP server that exposes all the management operations as tools. Add this to your MCP config:

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

Tools exposed (13): `list_cameras`, `discover_cameras`, `add_camera`, `remove_camera`, `list_streams`, `list_pipelines`, `get_pipeline`, `save_pipeline`, `delete_pipeline`, `start_pipeline`, `stop_pipeline`, `pipeline_status`, `node_catalog`, `recent_events`.

You can ask Claude things like "add a camera at rtsp://… called front_door" or "show me the last 10 events from the intrusion pipeline" and it'll use these tools.

---

## What runs where (mental model)

- **Capture** (camera drivers, FrameBus): runs in the backend Python process. Frames are numpy arrays in memory.
- **Streaming to browser**: each camera's frames go through GStreamer → H.264 → RTSP → MediaMTX → WebRTC → browser `<video>`. Three hops, sub-second end-to-end.
- **Pipelines**: each pipeline = an asyncio task per node. Edges = bounded asyncio queues with drop-oldest semantics for FRAME ports (so a slow detector never stalls capture) and keep-all for EVENT ports (so alerts aren't lost).
- **Persistence**: SQLite (cameras, pipelines, events, clips). Path is resolved relative to your config file.
- **Frontend**: React SPA, talks to backend over REST + SSE + WebSocket. WebRTC bypasses the backend, going straight to MediaMTX.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the deep dive.
