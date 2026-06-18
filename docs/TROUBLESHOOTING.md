# camera_dash — Troubleshooting

The most common failure modes, what causes them, and how to fix them. Many of these were real bugs hit during initial development — included here as future-you insurance.

---

## Backend won't start

### "Address already in use" on port 8001

Another app is on 8001 (or whatever you configured). Find what's there:

```bash
lsof -i :8001 -n -P
```

Either stop the other process or change `configs/deploy.*.yml` → `server.port` AND `frontend/vite.config.ts` → `server.proxy` target.

### "AssertionError" deep in `gi/overrides/GLib.py` on macOS

You're using python.org Python, which wraps everything in Python.app and strips `DYLD_FALLBACK_LIBRARY_PATH`. PyGObject can't find Homebrew's GLib.

**Fix**: recreate the venv with Homebrew Python:
```bash
rm -rf backend/.venv
/opt/homebrew/bin/python3.13 -m venv backend/.venv
backend/.venv/bin/pip install -e 'backend[mac,mcp,dev]' PyGObject
```

### `ImportError` for any extra (anthropic / supervision / depthai / easyocr)

These are optional. Either install them:
```bash
backend/.venv/bin/pip install <name>
```
…or remove the node that needs them from your pipeline.

### Backend takes ~20s to start

That's load_catalog() loading 39 entry-points; many transitively import torch/mediapipe/etc. on first reference. This is one-time per process; not a bug.

---

## Cameras don't show in the dashboard

### `/api/cameras` returns `[]` after backend restart

You used to have cameras but now they're gone. The DB path got relocated.

**Cause**: pre-fix, `storage.dsn` used a CWD-relative path. If you launched the backend from a different directory, a new empty DB got created.

**Fix** (done in code): `Settings.from_yaml` now resolves relative DSN paths against the config file's parent. Also `cli.py run` sets `$CAMERA_DASH_CONFIG` so the lifespan reads the same config.

**Recovery**: find the old DB:
```bash
find . -name "camera_dash.db*" -not -path "*/node_modules/*"
cp <old_path> data/camera_dash.db
```

### MediaMTX paths list is empty even though cameras are running

The streaming publishers didn't auto-attach on startup.

**Fix** (done in code): `main.py` lifespan now iterates `camera_manager.list()` after start and attaches a streaming publisher for each running camera.

If you still see this: check the backend log for the GStreamer pipeline line — if it's missing, the publisher didn't start. Look for `rtspclientsink` errors (often: MediaMTX isn't running yet, or the wrong port).

### Camera shows in `/api/cameras` but the tile is blank/empty in the browser

Three possibilities:

1. **MediaMTX isn't running.** `curl http://localhost:9997/v3/paths/list` → should not be connection-refused.
2. **WebRTC isn't reaching the browser.** Browser dev tools → Network → look for `whep` POSTs failing. Usually CORS or port mismatch.
3. **Stale browser bundle / localStorage.** Hard refresh (Cmd-Shift-R) and/or run `localStorage.clear(); location.reload()` in the dev console.

---

## Video doesn't play / aspect ratio wrong / can't resize

These were all real bugs in the first iteration. They've been fixed by:
- Switching from `react-grid-layout` to `react-rnd` for tile positioning
- Dropping `react-zoom-pan-pinch` (interfered with flexbox)
- Using a native `addEventListener('wheel', …, { passive: false })` instead of React's synthetic `onWheel` for zoom

If you see "Unable to preventDefault inside passive event listener invocation" in the console, it's harmless console noise — but if you're forking the code and added a new `onWheel`, that's the cause.

---

## FLIR thermal issues

### Temperature-on-hover shows nonsense values (e.g. -180°C)

The PureThermal is in **AGC mode**, not radiometric. The values aren't temperatures, just stretched 8-bit visual data.

**Fix**: download GroupGets' [PureThermal Lepton UVC Capture app](https://github.com/groupgets/purethermal1-uvc-capture), switch the camera to radiometric mode. The setting persists in the camera's firmware.

### "Lepton not connected" via flirpy

flirpy's macOS auto-detect parses `system_profiler SPCameraDataType` output looking for `VendorID_1E4E` but macOS reports vendor IDs in decimal (`VendorID_7758`). So flirpy's regex never matches.

**Fix** (done in code): we bypass flirpy entirely and use GStreamer's `avfvideosrc` with `format=GRAY16_LE` to grab the raw thermal frames. flirpy is still imported but not used for capture.

### FLIR keeps getting reassigned a different USB index

Don't rely on `device_index` — use `device_name: "PureThermal (fw:v1.0.0)"` in your camera params. The cameras code looks the device up by display name via `Gst.DeviceMonitor`.

---

## Pipeline editor

### "[React Flow]: Couldn't create edge for source handle id"

Race condition: the pipeline was loaded before the node catalog. Without the catalog, nodes mount without input/output handles, so React Flow can't wire the edges.

**Fix** (done in code): the editor defers loading the pipeline until `catalog.length > 0`.

### `/api/pipelines/templates` returns 404 "pipeline not found"

URL collision: `/api/pipelines/{id}` was registered before `/api/pipelines/templates`, so FastAPI treats "templates" as a pipeline id.

**Fix** (done in code): templates moved to `/api/templates` (not under `/api/pipelines`). Same for `/api/draft`.

### Pipelines validate fine via CLI but fail to start

Look for `Couldn't create edge` warnings (the React Flow ones above) — they often imply the pipeline JSON references handles that don't exist on the loaded node version. Compare the catalog's `inputs`/`outputs` for each node type to the edges in your pipeline.

---

## Recording

### Clips don't include pre-roll even though `pre_roll_s > 0`

Either:
1. **Ring buffer isn't running**: check the backend log for `ring buffer <camera_id> starting`. If absent, the recorder didn't acquire one (probably no `ring_buffers` in `NodeContext`).
2. **MediaMTX path doesn't exist**: the ring buffer's ffmpeg pulls from `rtsp://mediamtx/camera/<id>`. If the camera isn't being published, ffmpeg fails silently. Check `/api/streams` and MediaMTX's `/v3/paths/list`.

### "ffmpeg not found on PATH"

Install ffmpeg: `brew install ffmpeg` (mac) or `apt install ffmpeg` (linux). Already in the installer scripts.

### Clips show up but their mp4 is 0 bytes or unplayable

Usually because the ring buffer segments haven't accumulated yet (you just started the pipeline) and post-roll capture is failing. Look for ffmpeg stderr in the backend log.

---

## AI composer / vision_llm

### `/api/draft` returns 400 "ANTHROPIC_API_KEY not set"

Set the env var in the shell that runs the backend:
```bash
export ANTHROPIC_API_KEY=sk-...
./scripts/run.sh backend
```

### Vision LLM never fires

The `detector.vision_llm` node defaults to `trigger_only: true` — it only runs when its `trigger` input receives an Event. Wire a `condition.*` node's `match` output to the vision_llm's `trigger` input.

Also it throttles to one call per `min_interval_s` (default 30s) to avoid burning tokens.

---

## Notifications

### Telegram messages don't arrive

1. Did you message your bot first? Telegram won't deliver bot messages to a user who hasn't initiated chat.
2. Is the chat id correct? Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` after sending a message to your bot — the `chat.id` field is what you want.
3. Bot tokens look like `1234567:ABC...` — both parts required.

### ntfy.sh notifications don't arrive

1. Did you subscribe to your topic in the ntfy app?
2. Topic names are case-sensitive.
3. The free `ntfy.sh` server has rate limits — if you're spamming, you'll get throttled.

---

## Performance

### Pipeline runs but FPS is low / lag

Check `/api/stats` for actual frame rates. Typical bottlenecks:
- YOLO on CPU is slow; set `device: mps` (mac) or `device: cuda` (NVIDIA) on detector nodes.
- Running 3+ pipelines on the same camera with full-res YOLO inference will saturate. Use smaller models (`yolov8n` vs `yolov8x`) or downscale with `transform.resize` before the detector.
- The FrameBus drops oldest frames if a consumer is slow; that's correct (live video) but reduces effective fps.

### Backend uses lots of memory

Each running camera adds ~50MB (frame buffers + GStreamer). Each pipeline adds memory proportional to its largest detector (YOLOv8x is ~2GB on GPU, ~500MB on CPU). MediaMTX is small (~50MB).

For RPi: use `--rpi` install, stick to YOLOv8n or smaller, limit to 1-2 simultaneous pipelines.

---

## Tests

### `pytest` fails with import errors

You're probably running it outside the venv. Use:
```bash
backend/.venv/bin/pytest backend/tests/
```

13 tests should pass. Tests don't touch any optional deps (no torch / ultralytics / etc. needed).

---

## Diagnostic commands

When in doubt, run these and look for what's not 200:

```bash
# All three services healthy?
curl -s -o /dev/null -w "backend=%{http_code}\n" http://localhost:8001/health
curl -s -o /dev/null -w "frontend=%{http_code}\n" http://localhost:5173/
curl -s -o /dev/null -w "mediamtx=%{http_code}\n" http://localhost:9997/v3/paths/list

# What cameras are configured + running?
curl -s http://localhost:8001/api/cameras | python3 -m json.tool

# What pipelines are running?
curl -s http://localhost:8001/api/pipelines/status | python3 -m json.tool

# Live events firehose
curl -N http://localhost:8001/api/events/stream

# Backend log
tail -f /tmp/camera_dash_backend.log
```
