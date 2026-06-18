# camera_dash — Installation

There's a one-shot installer per platform that does everything. If you want the manual steps for understanding/customization, they're at the bottom.

## TL;DR

```bash
git clone <repo> camera_dash && cd camera_dash
bash scripts/dev-setup.sh   # auto-picks macos or linux

# Three services in three terminals:
./scripts/run.sh backend
./scripts/run.sh frontend
./scripts/run.sh mediamtx
```

Then open http://localhost:5173.

## Platforms

| Platform | Notes |
|---|---|
| macOS (Apple Silicon) | Tested; uses Homebrew |
| macOS (Intel) | Should work; uses Homebrew |
| Ubuntu 22.04 / 24.04 | Tested via apt |
| Debian 12 | Should work via apt |
| Raspberry Pi OS (bullseye/bookworm) | Use `--rpi` flag for lighter ML deps |
| Fedora 40+ | Should work via dnf |
| Arch / Manjaro | Should work via pacman |

NVIDIA DGX Spark + CUDA: see [GPU notes](#gpu-deployments) below.

## Installer flags

```
scripts/install-macos.sh             full install (recommended)
scripts/install-macos.sh --core      skip ML deps (smaller, faster)
scripts/install-macos.sh --no-mqtt   skip mosquitto MQTT broker

scripts/install-linux.sh             full install
scripts/install-linux.sh --core      skip ML deps
scripts/install-linux.sh --rpi       Raspberry Pi profile
```

`--core` drops `torch`/`ultralytics`/`mediapipe`/`depthai`/`easyocr` — if you don't need YOLO/pose/OAK/OCR, the install is much smaller (~50MB vs ~3GB).

## What gets installed

### System packages

- **GStreamer** (+ all plugins): camera capture, encoding, RTSP push
- **MediaMTX**: WebRTC/HLS/RTSP relay (Apple Silicon: brew; Linux: GitHub binary)
- **ffmpeg**: clip recording, thumbnails, time-lapse
- **libusb**: for thermal cameras (PureThermal/Lepton)
- **mosquitto** (optional): local MQTT broker for `sink.mqtt`
- **python@3.13** (macOS only; Linux uses distro Python)
- **Node.js + npm**: frontend dev server / build

### Python (in `backend/.venv`)

- Core: FastAPI, asyncio, SQLAlchemy 2, pydantic-settings, opencv-python-headless, numpy
- Inference: torch, ultralytics (YOLO + YOLO-World), onnxruntime, mediapipe
- Thermal: flirpy (still imported but our capture path is GStreamer)
- Tracking: supervision (ByteTrack)
- LLM: anthropic
- OAK: depthai
- OCR: easyocr
- MCP: mcp

### Frontend (in `frontend/node_modules`)

- React 18 + Vite + TypeScript + Tailwind 4
- React Flow (`@xyflow/react`) for pipeline editor
- react-rnd for dashboard tile positioning
- react-jsonschema-form for node config forms

## macOS-specific gotchas

The installer handles these for you, but worth knowing:

### 1. Use Homebrew Python, NOT python.org

python.org's Python wraps everything in `Python.app` which strips `DYLD_FALLBACK_LIBRARY_PATH`. PyGObject (the Python ↔ GStreamer bridge) needs that env var to find `libglib-2.0.0.dylib` at runtime. Result: `import gi` blows up with an `AssertionError` deep inside GLib overrides.

The installer specifically uses `/opt/homebrew/bin/python3.13` for the venv, avoiding this.

### 2. Camera permission

The first time the backend opens a camera, macOS pops a permission dialog asking you to grant **the parent app** (Terminal / iTerm / Warp) access. Approve it once, then it sticks.

If you previously denied: System Settings → Privacy & Security → Camera → toggle the relevant app.

### 3. PureThermal FLIR ships in AGC mode

Out of the box, the GroupGets PureThermal board outputs AGC (auto-gain-controlled) 8-bit data stretched into a 16-bit container. The temperature-on-hover overlay will show meaningless values (e.g. -185°C) until you flip the camera to **radiometric mode** with the [PureThermal Lepton UVC Capture app](https://github.com/groupgets/purethermal1-uvc-capture). It's a one-time setting; persists in the camera's firmware across power cycles.

### 4. USB device-index isn't stable across replugs

Always identify cameras by `device_name` (not `device_index`) in the params. The discover button in the Cameras tab shows you the names.

## Linux-specific gotchas

### Video group

Reading from `/dev/video*` requires `video` group membership. The installer adds your user to the group — you need to log out + back in for it to take effect.

### Raspberry Pi

- Use `--rpi` flag: skips torch/ultralytics (which are slow and large on ARM), keeps `onnxruntime` + `tflite-runtime` for inference.
- For the Pi Camera Module specifically, you'll want a `source.uvc` with `device: /dev/video0` after enabling the camera in raspi-config.
- The HQ camera benefits from setting `width: 1920, height: 1080, fps: 15` to keep CPU low.

## GPU deployments

For an NVIDIA box (Linux or DGX Spark):

```bash
# Inside backend/.venv after the base install:
pip install --upgrade -e 'backend[gpu]'
```

This pulls `torch>=2.5` with CUDA and `onnxruntime-gpu`. In your pipelines set `device: cuda` on detector nodes.

For Apple Silicon, the `[mac]` extra already includes `torch` with MPS support; set `device: mps`.

## Docker

```bash
docker compose up                          # backend + mediamtx + frontend
docker compose --profile with-mqtt up      # also start mosquitto
```

The compose file mounts `/dev` so USB cameras work on Linux hosts. On macOS, Docker can't access the host's cameras due to virtualization — run natively for camera support.

## Running on different ports

If 8000 / 5173 / 8554 / 8889 are taken, edit:
- Backend: `configs/deploy.<target>.yml` → `server.port`
- Frontend: `frontend/vite.config.ts` → `server.port` AND `server.proxy["/api"]` URL
- MediaMTX: `mediamtx/mediamtx.yml` → addresses

## Optional env vars

| Var | Used by | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | `detector.vision_llm`, `/api/draft` | Claude API |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | `sink.telegram` | Telegram bot |
| `PUSHOVER_APP_TOKEN` + `PUSHOVER_USER_KEY` | `sink.pushover` | Pushover push |
| `SMTP_USER` + `SMTP_PASSWORD` | `sink.email` | SMTP auth |
| `CAMERA_DASH_API` | `mcp_server.py` | URL of the backend if running MCP separately |
| `CAMERA_DASH_CONFIG` | backend lifespan | Path to deploy YAML (also settable via CLI `--config`) |

## Verifying the install

```bash
./scripts/run.sh all       # start all three
sleep 10
curl http://localhost:8001/health           # → {"status":"ok"}
curl http://localhost:9997/v3/paths/list    # → MediaMTX paths JSON
curl http://localhost:5173/                  # → HTML
```

Open `http://localhost:5173` and you should see the dashboard.

## Manual install (no scripts)

If you want to know exactly what's happening:

### macOS

```bash
brew install gstreamer mediamtx ffmpeg libusb python@3.13 node mosquitto
/opt/homebrew/bin/python3.13 -m venv backend/.venv
backend/.venv/bin/pip install -e 'backend[mac,mcp,dev]' PyGObject
(cd frontend && npm install)
```

### Ubuntu / Debian

```bash
sudo apt install -y python3 python3-venv python3-gi python3-gi-cairo \
  gstreamer1.0-tools gstreamer1.0-plugins-{base,good,bad,ugly} \
  gstreamer1.0-libav ffmpeg libusb-1.0-0 \
  libcairo2-dev libgirepository1.0-dev pkg-config \
  build-essential nodejs npm
# MediaMTX from GitHub releases (no apt package):
curl -sL https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_v*_linux_amd64.tar.gz | sudo tar xz -C /usr/local/bin mediamtx
python3 -m venv --system-site-packages backend/.venv
backend/.venv/bin/pip install -e 'backend[inference,thermal,mcp,dev]'
(cd frontend && npm install)
```

### Run

```bash
mediamtx mediamtx/mediamtx.yml &
backend/.venv/bin/python -m camera_dash.cli run --config configs/deploy.mac.yml &
(cd frontend && npm run dev) &
```
