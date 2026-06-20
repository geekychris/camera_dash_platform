#!/usr/bin/env bash
# Privileged backend launcher — invoked via sudo from `scripts/run.sh --privileged`.
#
# Why this exists: macOS's UVC stack only lets non-root processes use cameras
# through AVFoundation, which refuses to stream more than one camera per
# VID:PID model. To run multiple identical FLIR Leptons concurrently, the
# capture path has to talk to libusb/libuvc directly — and that requires
# root on macOS (kernel UVC claim, see flir_lepton.py).
#
# This script is intentionally tiny and accepts no arguments so the sudoers
# entry in /etc/sudoers.d/camera_dash_dev can grant exact-path NOPASSWD with
# no wildcards. Change anything here and the sudoers entry still matches —
# but anyone with write access to this file effectively has passwordless
# root, so don't relax permissions on it.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Hardcoded so the sudoers entry doesn't need to allow arbitrary args.
# Override-by-edit if your deploy profile differs — and re-run
# scripts/setup-passwordless-sudo.sh if the helper path changes.
CONFIG="${CAMERA_DASH_CONFIG:-configs/deploy.mac.yml}"
LOG="/tmp/camera_dash_backend.log"

# Fail fast if the venv isn't where we expect.
PY="backend/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "venv python not found at $PY — run scripts/install-macos.sh first" >&2
  exit 1
fi
if [[ ! -f "$CONFIG" ]]; then
  echo "config not found at $CONFIG" >&2
  exit 1
fi

# nohup + & + disown so the python keeps running after sudo exits.
nohup "$PY" -m camera_dash.cli run --config "$CONFIG" > "$LOG" 2>&1 &
disown

echo "backend started as root (pid $!, log $LOG, config $CONFIG)"
