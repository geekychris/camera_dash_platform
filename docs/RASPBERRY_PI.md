# camera_dash on a Raspberry Pi (with auto-start)

A walkthrough for installing `camera_dash` on a Raspberry Pi 5 (8GB used here)
and having it auto-start on boot via systemd. Tested on **Debian 13 Trixie /
Raspberry Pi OS Bookworm-based** with Python 3.13.

The end state: reach `http://<your-pi>.local:5173/` from any browser on the
LAN, no manual restart needed after reboots, services auto-recover from
crashes, logs go to `journalctl`.

## Pre-flight

You need:

- **SSH access** from your dev machine. Passwordless via key is best.
- **Sudo on the Pi**. If you want this whole process to be unattended (so the
  installer doesn't prompt for a password mid-way), make `chris` (your user)
  passwordless-sudo on the Pi:
  ```bash
  echo 'chris ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/chris-nopasswd
  sudo chmod 0440 /etc/sudoers.d/chris-nopasswd
  ```
  Adjust the username if yours differs. This is a security trade-off — fine
  for a homelab Pi, less so for a shared box.
- **A working internet connection** on the Pi for the apt + pip + npm
  downloads.

The installer pulls in a couple of GB across system packages, ML wheels,
and node_modules — give it ~5–10 minutes on a Pi 5, longer on a Pi 4.

## Install

From the Pi (or via SSH):

```bash
git clone https://github.com/geekychris/camera_dash_platform.git ~/camera_dash
cd ~/camera_dash
sudo bash scripts/install-linux.sh --rpi
sudo bash scripts/install-systemd.sh
```

That's it. The first script sets up:

- system packages (GStreamer, libusb, mosquitto, ffmpeg, build tools, node)
- a Python 3 venv in `backend/.venv` with `camera_dash[rpi,mcp,dev]`
- frontend `node_modules` via `npm install`
- the `mediamtx` binary (correct ARM64 release, auto-detected)
- your user added to the `video` group

The second script writes three systemd units and enables them. They start
immediately and will come back up on reboot.

| Unit | What it does |
|---|---|
| `camera_dash-mediamtx.service` | RTSP/HLS/WebRTC relay (`/usr/local/bin/mediamtx`) |
| `camera_dash-backend.service` | FastAPI + pipelines, depends on `mediamtx` |
| `camera_dash-frontend.service` | Vite dev server, listens on `0.0.0.0:5173` |

All three run as your user (whoever invoked `sudo`), not root.

## Verify

From your dev machine:

```bash
curl -fsS http://pi5-8.local:8001/health   # → "ok"
curl -fsS http://pi5-8.local:5173/         # → returns the index.html
```

Then open `http://pi5-8.local:5173/` in your browser.

`/api/cameras` will be empty until you plug something in and add it via the
Cameras tab.

## Day-to-day

```bash
# Watch logs
journalctl -u camera_dash-backend  -f
journalctl -u camera_dash-mediamtx -f
journalctl -u camera_dash-frontend -f

# Restart after a config change
sudo systemctl restart camera_dash-backend

# Restart everything
sudo systemctl restart camera_dash-{mediamtx,backend,frontend}

# Quick status
systemctl status camera_dash-backend

# Stop until further notice
sudo systemctl stop camera_dash-{mediamtx,backend,frontend}

# Uninstall the units (does not touch the repo or venv)
sudo bash scripts/install-systemd.sh --uninstall
```

After a `git pull` on the Pi, restart whichever services changed:

```bash
cd ~/camera_dash && git pull
sudo systemctl restart camera_dash-backend          # backend code change
sudo systemctl restart camera_dash-frontend         # frontend code change
```

If `pyproject.toml` or `package.json` changed you also need to update the
venv / node_modules — just re-run the installer:

```bash
sudo bash scripts/install-linux.sh --rpi
```

It's idempotent.

## Gotchas, in the order you might hit them

### 1. Vite 504 "Outdated Optimize Dep" errors in the browser console

Cause: `node_modules/.vite/` is owned by root because `install-linux.sh` ran
under sudo, but the systemd unit runs as your user. Your user can't write
the optimize cache, so every dependency 504s.

Fix:

```bash
sudo chown -R "$USER":"$USER" ~/camera_dash
sudo systemctl restart camera_dash-frontend
```

The installer (v2026-06-19+) auto-chowns at the end, so fresh installs
don't hit this. Older installs do — apply the chown above once.

### 2. `403 Forbidden` from `http://<pi>.local:5173/`

Cause: Vite 5.4+ blocks unknown Host headers (DNS-rebinding protection).
The repo's `vite.config.ts` sets `allowedHosts: true` to disable that for
self-hosted LAN use. If you're on an older checkout, pull or add the
setting.

### 3. Backend logs `Address already in use` on port 8001

Something else has 8001. Find it:

```bash
sudo lsof -iTCP:8001 -sTCP:LISTEN
```

Edit `configs/deploy.rpi.yml` to pick a different port, then update the
Vite proxy target in `frontend/vite.config.ts` to match, then
`sudo systemctl restart camera_dash-backend camera_dash-frontend`.

### 4. `tflite-runtime` install failure

If your Pi is on Python ≥ 3.13 you'll see `No matching distribution`. The
pyproject gates that wheel on `python_version < '3.13'` so the failure
shouldn't happen on current main. If you're on an older checkout, just
ignore it — `onnxruntime` is the inference fallback.

### 5. `freenect` Python wrapper for the Kinect 360

Not installed by default. If you have a Kinect 360 plugged in:

```bash
sudo bash scripts/install-linux.sh --with-kinect
sudo systemctl restart camera_dash-backend
```

The `freenect` wrapper builds from libfreenect's `wrappers/python` tree
and is gated to Python ≥ 3.13 with a setup.py patch.

### 6. Cameras not visible in the Discover tab

Make sure your user is in the `video` group (`groups | grep video`). If you
just added yourself, **log out and back in** — or just reboot. Group
membership doesn't take effect on existing sessions.

### 7. After a reboot, services say `failed`

Most common cause: the venv path baked into the unit file no longer
matches the file system (e.g. you renamed `~/camera_dash`). Re-run
`sudo bash scripts/install-systemd.sh` to regenerate the unit files with
the current path, then `sudo systemctl daemon-reload` and start again.

## What's different from the Mac install

| | Mac | Pi |
|---|---|---|
| Auto-start | `./scripts/run.sh all` (foreground/dev) | systemd units (boot/prod) |
| Backend port | 8001 | 8001 (since this commit; was 8000) |
| Camera permission | `Settings → Privacy → Camera` | `video` group |
| Multi-FLIR | broken on Tahoe beta (libuvc crashes) | works via V4L2, no root needed |
| Kinect 360 | works after sudoers + libfreenect | works once `--with-kinect` runs |
| Frontend access | `http://localhost:5173` | `http://<pi>.local:5173` |
| Logs | `/tmp/camera_dash_*.log` | `journalctl -u camera_dash-*` |

## Bigger picture: where to next

This setup runs Vite in dev mode for the frontend — convenient (HMR works,
no build step needed) but uses ~300MB extra RAM on the Pi. For a real
production deploy you'd typically:

- `npm run build` once
- serve the built `dist/` via nginx or a Python static-files mount on the
  backend
- drop the `camera_dash-frontend.service` unit

That's a follow-up — the current setup is fast to bring up and easy to
iterate on.
