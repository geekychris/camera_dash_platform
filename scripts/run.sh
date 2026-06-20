#!/usr/bin/env bash
# Convenience launcher.
#
# Usage:
#   ./scripts/run.sh all                    # backend + frontend + mediamtx in background
#   ./scripts/run.sh all --privileged       # backend launched as root via sudo
#                                           #   (required for multi-FLIR on macOS — see flir_lepton.py).
#                                           #   Run scripts/setup-passwordless-sudo.sh once so it
#                                           #   doesn't prompt for a password.
#   ./scripts/run.sh backend                # foreground backend
#   ./scripts/run.sh frontend               # foreground frontend dev server
#   ./scripts/run.sh mediamtx               # foreground MediaMTX
#   ./scripts/run.sh stop [--privileged]    # stop everything; use --privileged if you started that way

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PRIVILEGED=false
POSITIONAL=()
for arg in "$@"; do
  case "$arg" in
    --privileged) PRIVILEGED=true ;;
    *) POSITIONAL+=("$arg") ;;
  esac
done
set -- "${POSITIONAL[@]}"

# Pick the deploy profile based on platform
case "$(uname -s)" in
  Darwin)  CONFIG="configs/deploy.mac.yml" ;;
  Linux)
    if [[ -e /sys/firmware/devicetree/base/model ]] && grep -qi "raspberry" /sys/firmware/devicetree/base/model 2>/dev/null; then
      CONFIG="configs/deploy.rpi.yml"
    else
      CONFIG="configs/deploy.dgx.yml"
    fi
    ;;
  *) echo "Unsupported OS"; exit 1 ;;
esac

BACKEND_LOG="/tmp/camera_dash_backend.log"
MEDIAMTX_LOG="/tmp/camera_dash_mediamtx.log"
FRONTEND_LOG="/tmp/camera_dash_frontend.log"

start_mediamtx() {
  if pgrep -f "mediamtx .*mediamtx.yml" >/dev/null; then
    echo "mediamtx already running"
    return
  fi
  nohup mediamtx mediamtx/mediamtx.yml > "$MEDIAMTX_LOG" 2>&1 &
  echo "mediamtx started — pid=$!  log=$MEDIAMTX_LOG"
}

start_backend() {
  if pgrep -f "camera_dash.cli run" >/dev/null; then
    echo "backend already running"
    return
  fi
  if $PRIVILEGED; then
    # -n means "non-interactive": if the sudoers entry isn't set up, fail
    # immediately rather than hang waiting for a password. The helper script
    # is intentionally tiny + takes no arguments so the sudoers rule can
    # grant exact-path NOPASSWD with no wildcards.
    if ! sudo -n scripts/_root-backend-start.sh; then
      cat >&2 <<'EOF'

✗ Privileged start failed. The sudoers entry isn't installed (or expired).
  Run once:

      sudo bash scripts/setup-passwordless-sudo.sh

  Then re-run:  ./scripts/run.sh all --privileged

EOF
      exit 1
    fi
  else
    nohup backend/.venv/bin/python -m camera_dash.cli run --config "$CONFIG" > "$BACKEND_LOG" 2>&1 &
    echo "backend started — pid=$!  log=$BACKEND_LOG  config=$CONFIG"
  fi
}

start_frontend() {
  if pgrep -f "vite" >/dev/null; then
    echo "frontend already running"
    return
  fi
  (cd frontend && nohup npm run dev > "$FRONTEND_LOG" 2>&1 &)
  echo "frontend starting — log=$FRONTEND_LOG"
}

stop_all() {
  pkill -f "vite" 2>/dev/null || true
  if $PRIVILEGED; then
    # Root processes need root to die; the helper handles SIGTERM → SIGKILL.
    if ! sudo -n scripts/_root-backend-stop.sh; then
      echo "warning: privileged stop failed (sudoers missing?); trying user pkill" >&2
      pkill -f "camera_dash.cli run" 2>/dev/null || true
    fi
  else
    pkill -f "camera_dash.cli run" 2>/dev/null || true
  fi
  pkill -f "mediamtx .*mediamtx.yml" 2>/dev/null || true
  echo "stopped"
}

case "${1:-all}" in
  all)
    start_mediamtx
    start_backend
    start_frontend
    echo
    echo "All three services starting. Health check in ~10s:"
    echo "  curl http://localhost:8001/health   (backend)"
    echo "  curl http://localhost:5173/         (frontend)"
    echo "  curl http://localhost:9997/v3/paths/list  (mediamtx)"
    echo
    echo "Then open http://localhost:5173"
    ;;
  backend)   exec backend/.venv/bin/python -m camera_dash.cli run --config "$CONFIG" ;;
  frontend)  cd frontend && exec npm run dev ;;
  mediamtx)  exec mediamtx mediamtx/mediamtx.yml ;;
  stop)      stop_all ;;
  logs)
    echo "=== backend ==="; tail -n 20 "$BACKEND_LOG" 2>/dev/null
    echo "=== mediamtx ==="; tail -n 20 "$MEDIAMTX_LOG" 2>/dev/null
    echo "=== frontend ==="; tail -n 20 "$FRONTEND_LOG" 2>/dev/null
    ;;
  *) echo "usage: $0 {all|backend|frontend|mediamtx|stop|logs} [--privileged]"; exit 1 ;;
esac
