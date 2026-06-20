#!/usr/bin/env bash
# Install libfreenect + the Python wrapper so the camera_dash kinect_v1 driver works.
#
# What it does:
#   1. Installs libfreenect (Homebrew on macOS, distro package on Linux)
#   2. Clones libfreenect (only its wrappers/python tree is needed)
#   3. Builds the Python binding against the system libfreenect and pip-installs
#      it into the camera_dash backend venv at backend/.venv
#
# Usage:
#   bash scripts/install-kinect-v1.sh                 # default venv at backend/.venv
#   VENV=backend/.venv bash scripts/install-kinect-v1.sh
#
# Idempotent: re-running just re-pulls the libfreenect tree and rebuilds the
# wrapper. Safe to skip if `python -c "import freenect"` already succeeds.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="${VENV:-backend/.venv}"
# Resolve to an absolute path so subsequent `cd` calls don't break the venv refs.
case "$VENV" in
  /*) ;;
  *) VENV="$REPO_ROOT/$VENV" ;;
esac
PYBIN="$VENV/bin/python"
PIPBIN="$VENV/bin/pip"

log() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
err() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

if [[ ! -x "$PYBIN" ]]; then
  err "venv python not found at $PYBIN — run scripts/install-macos.sh or scripts/install-linux.sh first"
  exit 1
fi

# ---------- Already installed? ----------
if "$PYBIN" -c "import freenect" >/dev/null 2>&1; then
  log "freenect Python wrapper already importable — nothing to do."
  exit 0
fi

# ---------- libfreenect (system lib) ----------
OS="$(uname -s)"
case "$OS" in
  Darwin)
    if ! command -v brew >/dev/null; then
      err "Homebrew not found; install it first or install libfreenect manually."
      exit 1
    fi
    log "Installing libfreenect via Homebrew…"
    brew list libfreenect >/dev/null 2>&1 || brew install libfreenect
    LIBFREENECT_PREFIX="$(brew --prefix libfreenect)"
    ;;
  Linux)
    if command -v apt-get >/dev/null; then
      log "Installing libfreenect via apt…"
      sudo apt-get update -qq
      sudo apt-get install -y --no-install-recommends libfreenect-dev libfreenect0.5 cython3
    elif command -v dnf >/dev/null; then
      log "Installing libfreenect via dnf…"
      sudo dnf install -y libfreenect libfreenect-devel
    elif command -v pacman >/dev/null; then
      log "Installing libfreenect via pacman…"
      sudo pacman -Sy --noconfirm libfreenect
    else
      err "Unsupported Linux distro — install libfreenect manually."
      exit 1
    fi
    LIBFREENECT_PREFIX="/usr"
    ;;
  *)
    err "Unsupported OS: $OS"
    exit 1
    ;;
esac

log "libfreenect at $LIBFREENECT_PREFIX"

# ---------- Build tools in the venv ----------
log "Ensuring cython>=3 + numpy in the venv (build-time deps for the wrapper)…"
# Force-upgrade cython — a Cython 0.x already present (from another package)
# emits a stale freenect.c whose _PyLong_AsByteArray call doesn't match Python
# 3.13's new 6-arg signature. Leave numpy alone if already installed —
# upgrading it can break sibling deps (e.g. flirpy pins numpy<2.4).
"$PIPBIN" install -q --upgrade pip
"$PIPBIN" install -q --upgrade "cython>=3"
"$PYBIN" -c "import numpy" 2>/dev/null || "$PIPBIN" install -q numpy

# ---------- libfreenect source for the Python wrapper ----------
SRC="${LIBFREENECT_SRC:-/tmp/libfreenect-src}"
if [[ -d "$SRC/.git" ]]; then
  log "Updating existing libfreenect checkout at ${SRC}…"
  git -C "$SRC" fetch --depth 1 origin master
  git -C "$SRC" reset --hard FETCH_HEAD
else
  log "Cloning libfreenect into ${SRC}…"
  rm -rf "$SRC"
  git clone --depth 1 https://github.com/OpenKinect/libfreenect.git "$SRC"
fi

cd "$SRC/wrappers/python"

# Patch setup.py to use Cython.__version__ instead of the legacy
# Cython.Compiler.Main.{Version,version} attributes (gone in Cython 3.x). With
# Cython 3 in the venv we want the build to actually invoke Cython, not fall
# back to the stale pre-generated freenect.c (which calls a 5-arg form of
# _PyLong_AsByteArray that Python 3.13 removed).
if grep -q 'Cython.Compiler.Main.version' setup.py; then
  log "Patching setup.py for Cython 3 compatibility…"
  "$PYBIN" - <<'PY'
import pathlib
p = pathlib.Path("setup.py")
src = p.read_text()
old = (
    "    try:\n"
    "        # old way, fails for me\n"
    "        version = Cython.Compiler.Main.Version.version\n"
    "    except AttributeError:\n"
    "        version = Cython.Compiler.Main.version\n"
)
new = (
    "    try:\n"
    "        version = Cython.Compiler.Main.Version.version\n"
    "    except AttributeError:\n"
    "        try:\n"
    "            version = Cython.Compiler.Main.version\n"
    "        except AttributeError:\n"
    "            import Cython as _C\n"
    "            version = _C.__version__\n"
)
if old in src:
    p.write_text(src.replace(old, new))
    print("setup.py patched")
else:
    print("setup.py already patched or has a different shape; skipping")
PY
fi

# Force Cython to regenerate freenect.c — the version checked in to the repo
# was generated against an older Cython and Python and won't compile under
# Python 3.13.
rm -f freenect.c

# The wrapper's setup.py respects CFLAGS/LDFLAGS for its single C extension —
# point it at the system libfreenect we just installed so it doesn't try to
# pkg-config against an out-of-PATH copy.
log "Building + installing freenect Python wrapper into ${VENV}…"

EXTRA_INCLUDE=""
EXTRA_LIB=""
if [[ "$OS" == "Darwin" ]]; then
  # The macOS linker doesn't search /opt/homebrew by default; libusb lives
  # there. setup.py hard-codes the link spec as `usb-1.0` (no path), so we
  # must surface the brew lib + include dirs via LDFLAGS/CFLAGS.
  LIBUSB_PREFIX="$(brew --prefix libusb 2>/dev/null || true)"
  if [[ -n "$LIBUSB_PREFIX" ]]; then
    EXTRA_INCLUDE="-I$LIBUSB_PREFIX/include -I$LIBUSB_PREFIX/include/libusb-1.0"
    EXTRA_LIB="-L$LIBUSB_PREFIX/lib"
  fi
fi

CFLAGS="-I$LIBFREENECT_PREFIX/include -I$LIBFREENECT_PREFIX/include/libfreenect $EXTRA_INCLUDE" \
LDFLAGS="-L$LIBFREENECT_PREFIX/lib -lfreenect $EXTRA_LIB" \
"$PIPBIN" install --no-build-isolation .

cd "$REPO_ROOT"

# ---------- Verify ----------
log "Verifying…"
if "$PYBIN" -c "import freenect; print('freenect module ok')"; then
  echo
  log "Done. Add a kinect_v1 camera in the dashboard (Camera Manager → kind: Kinect 360 (v1))."
  echo
  cat <<'EOF'
On macOS, the kernel UVC driver may auto-claim the device. If `freenect.sync_get_depth`
returns immediately with no data, plug the Kinect into a different USB port (avoid hubs)
or run `sudo killall VDCAssistant` and retry. The Kinect's external power brick must be
plugged in — it doesn't run off USB power alone.
EOF
else
  err "freenect import failed after install — check the build output above."
  exit 1
fi
