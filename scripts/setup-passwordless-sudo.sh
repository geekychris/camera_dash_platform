#!/usr/bin/env bash
# Install a narrowly-scoped sudoers entry so `scripts/run.sh --privileged`
# can start/stop the camera_dash backend as root without prompting.
#
# This is needed only on macOS — multi-FLIR concurrent capture talks to USB
# via libuvc, which needs root to override macOS's VDCAssistant UVC claim.
# Linux v4l2 doesn't have the restriction; you don't need this script there.
#
# What it does:
#   1. Computes absolute paths to scripts/_root-backend-start.sh and -stop.sh
#   2. Writes a temp file with two NOPASSWD lines, scoped to those two paths
#   3. Validates the file via `visudo -cf`
#   4. Installs it at /etc/sudoers.d/camera_dash_dev (mode 0440)
#
# Usage:
#   sudo bash scripts/setup-passwordless-sudo.sh
#
# Remove with:
#   sudo rm /etc/sudoers.d/camera_dash_dev

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "✗ Must be run with sudo (we're writing /etc/sudoers.d/camera_dash_dev)." >&2
  echo "  Try:  sudo bash scripts/setup-passwordless-sudo.sh" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
START="$REPO_ROOT/scripts/_root-backend-start.sh"
STOP="$REPO_ROOT/scripts/_root-backend-stop.sh"

if [[ ! -x "$START" || ! -x "$STOP" ]]; then
  echo "✗ Helper scripts not found or not executable:" >&2
  echo "    $START" >&2
  echo "    $STOP" >&2
  echo "  Run from a clean repo checkout." >&2
  exit 1
fi

# Use the real user even when run via sudo (SUDO_USER), so the rule grants
# the user who's actually working, not the root account.
REAL_USER="${SUDO_USER:-$USER}"
if [[ -z "$REAL_USER" || "$REAL_USER" == "root" ]]; then
  echo "✗ Couldn't determine the real user — please re-run via sudo from your normal shell." >&2
  exit 1
fi

OUT_PATH="/etc/sudoers.d/camera_dash_dev"
TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

cat > "$TMP_FILE" <<EOF
# camera_dash dev passwordless sudo (managed by setup-passwordless-sudo.sh)
#
# Lets $REAL_USER start/stop the backend as root via two specific helper
# scripts — no other command receives elevated privileges. Required for
# multi-FLIR concurrent capture on macOS (libuvc / VDCAssistant claim).
#
# Remove with: sudo rm $OUT_PATH

$REAL_USER ALL=(root) NOPASSWD: $START
$REAL_USER ALL=(root) NOPASSWD: $STOP
EOF

# Sudoers files must be syntactically valid AND mode 0440 with root:wheel.
if ! visudo -cf "$TMP_FILE" > /dev/null; then
  echo "✗ Generated sudoers file failed visudo validation:" >&2
  cat "$TMP_FILE" >&2
  exit 1
fi

install -m 0440 -o root -g wheel "$TMP_FILE" "$OUT_PATH"

cat <<EOF

✓ Installed $OUT_PATH

  $REAL_USER can now run as root without a password:
    $START
    $STOP

To exercise the new rule:
    ./scripts/run.sh stop --privileged
    ./scripts/run.sh all  --privileged

To uninstall:
    sudo rm $OUT_PATH

EOF
