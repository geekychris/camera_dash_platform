#!/usr/bin/env bash
# One-shot installer that picks the right script for the host.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
case "$(uname -s)" in
  Darwin) exec bash scripts/install-macos.sh "$@" ;;
  Linux)  exec bash scripts/install-linux.sh "$@" ;;
  *) echo "Unsupported OS: $(uname -s)"; exit 1 ;;
esac
