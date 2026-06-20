#!/usr/bin/env bash
# camera_dash — macOS installer (Apple Silicon + Intel)
#
# What it does:
#   1. Ensures Homebrew is present
#   2. Installs system deps: gstreamer (bundles plugins + pygobject3),
#      mediamtx, ffmpeg, mosquitto (optional), libusb, python@3.13, node
#   3. Creates a Python venv with Homebrew Python (NOT python.org —
#      python.org's Python.app strips DYLD_FALLBACK_LIBRARY_PATH and
#      breaks PyGObject's runtime load of GLib)
#   4. Installs camera_dash[mac,mcp,dev] + PyGObject + extras
#   5. Installs frontend node deps
#
# Usage:
#   bash scripts/install-macos.sh                # full install
#   bash scripts/install-macos.sh --core         # skip ML deps (smaller, faster)
#   bash scripts/install-macos.sh --no-mqtt      # skip mosquitto
#   bash scripts/install-macos.sh --with-kinect  # also install libfreenect + freenect Python wrapper

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CORE_ONLY=false
WITH_MQTT=true
WITH_KINECT=false
for arg in "$@"; do
  case "$arg" in
    --core) CORE_ONLY=true ;;
    --no-mqtt) WITH_MQTT=false ;;
    --with-kinect) WITH_KINECT=true ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
  esac
done

log() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
err() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

# ---------- Homebrew ----------
if ! command -v brew >/dev/null; then
  log "Installing Homebrew (one-time)…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

BREW_PREFIX="$(brew --prefix)"
log "Homebrew at $BREW_PREFIX"

# ---------- System packages ----------
log "Installing system dependencies via brew…"
PKGS=(gstreamer mediamtx ffmpeg libusb python@3.13 node)
$WITH_MQTT && PKGS+=(mosquitto)
brew install "${PKGS[@]}" || true
brew upgrade gstreamer mediamtx ffmpeg python@3.13 node 2>/dev/null || true

# Sanity-check critical binaries
for bin in gst-launch-1.0 mediamtx ffmpeg python3.13 node npm; do
  if ! command -v "$bin" >/dev/null; then
    err "$bin not on PATH after brew install — check /opt/homebrew/bin"
    exit 1
  fi
done

# ---------- Python venv ----------
PY="$BREW_PREFIX/bin/python3.13"
log "Creating venv with $PY"
"$PY" -m venv backend/.venv
PIP="backend/.venv/bin/pip"
"$PIP" install -q --upgrade pip

EXTRAS="[mac,mcp,dev]"
$CORE_ONLY && EXTRAS="[mcp,dev]"
log "Installing camera_dash$EXTRAS + PyGObject (this can take a few minutes)…"
"$PIP" install -q -e "backend$EXTRAS" PyGObject

if ! $CORE_ONLY; then
  log "Installing optional ML extras (supervision, anthropic, depthai, easyocr)…"
  "$PIP" install -q supervision anthropic depthai easyocr || warn "Some optional deps failed — re-run with --core to skip ML"
fi

# ---------- Frontend ----------
log "Installing frontend node deps…"
(cd frontend && npm install --silent --no-audit --no-fund)

# ---------- Optional: Kinect 360 (v1) ----------
if $WITH_KINECT; then
  log "Installing libfreenect + freenect Python wrapper for Kinect 360 support…"
  bash scripts/install-kinect-v1.sh
fi

# ---------- Summary ----------
cat <<EOF

$(printf '\033[1;32m✓ camera_dash installed.\033[0m')

To run, open three terminals:

  # 1. MediaMTX (streaming relay)
  mediamtx mediamtx/mediamtx.yml

  # 2. Backend
  ./scripts/run.sh backend

  # 3. Frontend
  ./scripts/run.sh frontend

Then open http://localhost:5173 in your browser.

Optional one-time setup:
  • Grant Camera permission to your Terminal app
    (System Settings → Privacy & Security → Camera)
  • Set ANTHROPIC_API_KEY for AI pipeline composer + vision_llm detector
  • Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID for sink.telegram

EOF
