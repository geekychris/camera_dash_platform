#!/usr/bin/env bash
# Install systemd units so camera_dash auto-starts on boot.
#
# What it creates:
#   /etc/systemd/system/camera_dash-mediamtx.service     (MediaMTX relay)
#   /etc/systemd/system/camera_dash-backend.service      (FastAPI + pipelines)
#   /etc/systemd/system/camera_dash-frontend.service     (Vite dev server)
#
# Each runs as the invoking user (SUDO_USER), in the current repo directory.
# Re-running this script regenerates the units in place — safe to do after
# moving the repo or changing the user.
#
# Usage:
#   sudo bash scripts/install-systemd.sh                # install + enable
#   sudo bash scripts/install-systemd.sh --no-enable    # install only
#   sudo bash scripts/install-systemd.sh --uninstall    # remove the units
#
# Logs:
#   journalctl -u camera_dash-backend -f
#   journalctl -u camera_dash-mediamtx -f
#   journalctl -u camera_dash-frontend -f

set -euo pipefail

ENABLE=true
UNINSTALL=false
for arg in "$@"; do
  case "$arg" in
    --no-enable) ENABLE=false ;;
    --uninstall) UNINSTALL=true ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "✗ Must be run with sudo (writing to /etc/systemd/system/)." >&2
  echo "  Try:  sudo bash scripts/install-systemd.sh" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REAL_USER="${SUDO_USER:-$USER}"
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
  echo "✗ Could not determine the real user. Run via sudo from your normal shell." >&2
  exit 1
fi

UNITS=(camera_dash-mediamtx camera_dash-backend camera_dash-frontend)

if $UNINSTALL; then
  for u in "${UNITS[@]}"; do
    systemctl stop "$u" 2>/dev/null || true
    systemctl disable "$u" 2>/dev/null || true
    rm -f "/etc/systemd/system/$u.service"
    echo "  removed $u"
  done
  systemctl daemon-reload
  echo "✓ Uninstalled camera_dash systemd units"
  exit 0
fi

# Resolve absolute paths the units will hardcode. These need to be stable so
# the units don't break if `which` resolves differently at runtime.
MEDIAMTX="$(sudo -u "$REAL_USER" bash -lc 'command -v mediamtx' 2>/dev/null || true)"
NPM="$(sudo -u "$REAL_USER" bash -lc 'command -v npm' 2>/dev/null || true)"
VENV_PY="$REPO_ROOT/backend/.venv/bin/python"

# Pick deploy profile based on platform — same logic as scripts/run.sh.
CONFIG="configs/deploy.dgx.yml"
if [[ -e /sys/firmware/devicetree/base/model ]] && grep -qi "raspberry" /sys/firmware/devicetree/base/model 2>/dev/null; then
  CONFIG="configs/deploy.rpi.yml"
fi

# Sanity-check.
if [[ ! -x "$VENV_PY" ]]; then
  echo "✗ Backend venv not found at $VENV_PY — run scripts/install-linux.sh first." >&2
  exit 1
fi
if [[ -z "$MEDIAMTX" ]]; then
  echo "⚠  mediamtx not on \$PATH for user $REAL_USER. Install it before starting the service." >&2
  MEDIAMTX="/usr/local/bin/mediamtx"
fi
if [[ -z "$NPM" ]]; then
  echo "✗ npm not on \$PATH for user $REAL_USER." >&2
  exit 1
fi

write_unit() {
  local name="$1" content="$2"
  echo "$content" > "/etc/systemd/system/$name.service"
  chmod 644 "/etc/systemd/system/$name.service"
  echo "  wrote /etc/systemd/system/$name.service"
}

write_unit camera_dash-mediamtx "[Unit]
Description=camera_dash MediaMTX (RTSP/HLS/WebRTC relay)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$REPO_ROOT
ExecStart=$MEDIAMTX $REPO_ROOT/mediamtx/mediamtx.yml
Restart=on-failure
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target"

write_unit camera_dash-backend "[Unit]
Description=camera_dash backend (FastAPI + pipelines)
After=network-online.target camera_dash-mediamtx.service
Wants=network-online.target
Requires=camera_dash-mediamtx.service

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$REPO_ROOT
Environment=CAMERA_DASH_CONFIG=$CONFIG
ExecStart=$VENV_PY -m camera_dash.cli run --config $CONFIG
Restart=on-failure
RestartSec=3
StandardOutput=journal
StandardError=journal
# Camera devices need supplementary group access on Linux.
SupplementaryGroups=video plugdev

[Install]
WantedBy=multi-user.target"

write_unit camera_dash-frontend "[Unit]
Description=camera_dash frontend (Vite dev server)
After=network-online.target camera_dash-backend.service

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$REPO_ROOT/frontend
ExecStart=$NPM run dev -- --host 0.0.0.0 --port 5173
Restart=on-failure
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target"

systemctl daemon-reload

if $ENABLE; then
  for u in "${UNITS[@]}"; do
    systemctl enable "$u" 2>&1 | grep -v "Created symlink" || true
  done
  systemctl restart camera_dash-mediamtx camera_dash-backend camera_dash-frontend
  echo
  echo "✓ Services installed and started."
else
  echo
  echo "✓ Services installed (not enabled — pass without --no-enable to enable + start)."
fi

HOST="$(hostname).local"
cat <<EOF

Watch a service:
    journalctl -u camera_dash-backend  -f
    journalctl -u camera_dash-mediamtx -f
    journalctl -u camera_dash-frontend -f

Quick status:
    systemctl status camera_dash-backend

Open the dashboard:
    http://$HOST:5173/

Restart everything:
    sudo systemctl restart camera_dash-backend camera_dash-mediamtx camera_dash-frontend

Uninstall:
    sudo bash scripts/install-systemd.sh --uninstall

EOF
