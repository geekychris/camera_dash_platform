#!/usr/bin/env bash
# Convenience launcher.
#
# Usage:
#   ./scripts/run.sh all          # start everything (backend, mediamtx, frontend) in background
#   ./scripts/run.sh backend      # foreground backend
#   ./scripts/run.sh frontend     # foreground frontend dev server
#   ./scripts/run.sh mediamtx     # foreground MediaMTX
#   ./scripts/run.sh stop         # stop everything

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

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
  nohup backend/.venv/bin/python -m camera_dash.cli run --config "$CONFIG" > "$BACKEND_LOG" 2>&1 &
  echo "backend started — pid=$!  log=$BACKEND_LOG  config=$CONFIG"
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
  pkill -f "camera_dash.cli run" 2>/dev/null || true
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
  *) echo "usage: $0 {all|backend|frontend|mediamtx|stop|logs}"; exit 1 ;;
esac
