#!/usr/bin/env bash
# Privileged backend killer — invoked via sudo from `scripts/run.sh stop --privileged`.
#
# A user-mode pkill can't terminate a process running as root, so when the
# backend was started privileged we need a privileged stop too. Intentionally
# no arguments for the same reason as the start helper.

set -euo pipefail

# Match the cli command exactly so we don't accidentally hit unrelated
# python processes.
pkill -f "camera_dash.cli run" 2>/dev/null || true
# Give the SIGTERM a moment; SIGKILL stragglers if the engine hangs.
sleep 1
pkill -9 -f "camera_dash.cli run" 2>/dev/null || true

echo "backend stopped (root)"
