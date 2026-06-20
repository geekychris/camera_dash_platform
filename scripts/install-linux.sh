#!/usr/bin/env bash
# camera_dash — Linux installer (Debian/Ubuntu, Fedora, Arch)
#
# Detects the package manager and installs system deps, then sets up a Python
# venv and installs camera_dash + frontend node deps.
#
# Tested on: Ubuntu 22.04/24.04, Debian 12, Raspberry Pi OS, Fedora 40, Arch.
#
# Usage:
#   sudo bash scripts/install-linux.sh                # full install
#   sudo bash scripts/install-linux.sh --core         # skip ML deps (RPi-friendly)
#   sudo bash scripts/install-linux.sh --rpi          # use camera_dash[rpi] extras
#   sudo bash scripts/install-linux.sh --with-kinect  # also install libfreenect + freenect Python wrapper

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CORE_ONLY=false
RPI=false
WITH_KINECT=false
for arg in "$@"; do
  case "$arg" in
    --core) CORE_ONLY=true ;;
    --rpi) RPI=true; CORE_ONLY=true ;;
    --with-kinect) WITH_KINECT=true ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
  esac
done

log() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
err() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

if [[ $EUID -ne 0 ]] && command -v sudo >/dev/null; then
  warn "Re-running under sudo for package install…"
  exec sudo --preserve-env=PATH "$0" "$@"
fi

# ---------- Detect distro ----------
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  DISTRO_ID="$ID"
  DISTRO_LIKE="${ID_LIKE:-}"
else
  err "Cannot detect distribution"
  exit 1
fi

log "Detected: $DISTRO_ID ($PRETTY_NAME)"

# ---------- System packages ----------
install_apt() {
  apt-get update
  PKGS=(
    python3 python3-venv python3-pip python3-gi python3-gi-cairo
    gir1.2-gst-plugins-base-1.0 gir1.2-gstreamer-1.0
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
    gstreamer1.0-x gstreamer1.0-alsa gstreamer1.0-pulseaudio
    ffmpeg libusb-1.0-0 libusb-1.0-0-dev
    libcairo2-dev libgirepository1.0-dev pkg-config
    build-essential nodejs npm curl
  )
  apt-get install -y --no-install-recommends "${PKGS[@]}"
  # Optional MQTT broker
  apt-get install -y --no-install-recommends mosquitto || warn "mosquitto skipped"
  # MediaMTX is not in apt — install binary
  install_mediamtx_binary
}

install_dnf() {
  dnf install -y \
    python3 python3-virtualenv python3-pip python3-gobject \
    gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good \
    gstreamer1-plugins-bad-free gstreamer1-plugins-ugly-free gstreamer1-libav \
    ffmpeg libusb1 libusb1-devel \
    cairo-devel gobject-introspection-devel pkgconf-pkg-config \
    nodejs npm gcc gcc-c++ make curl mosquitto
  install_mediamtx_binary
}

install_pacman() {
  pacman -Sy --noconfirm \
    python python-pip python-gobject \
    gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-libav \
    ffmpeg libusb \
    cairo gobject-introspection pkgconf \
    nodejs npm base-devel curl mosquitto mediamtx
}

install_mediamtx_binary() {
  if command -v mediamtx >/dev/null; then return; fi
  log "Installing MediaMTX binary (latest GitHub release)…"
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64) MTX_ARCH=amd64 ;;
    # MediaMTX renamed the aarch64 release asset around v1.19 — used to be
    # "arm64v8" but is now just "arm64". The api.github.com path is also
    # rate-limited; resolve the latest tag via redirect instead.
    aarch64|arm64) MTX_ARCH=arm64 ;;
    armv7l) MTX_ARCH=armv7 ;;
    *) err "Unsupported arch $ARCH for MediaMTX prebuilt"; return 1 ;;
  esac
  VER=$(curl -sSL -o /dev/null -w "%{url_effective}" "https://github.com/bluenviron/mediamtx/releases/latest" \
        | sed -E 's|.*/tag/(v[0-9.]+).*|\1|')
  if [[ -z "$VER" || "$VER" == https* ]]; then err "Could not resolve MediaMTX latest version"; return 1; fi
  URL="https://github.com/bluenviron/mediamtx/releases/download/${VER}/mediamtx_${VER}_linux_${MTX_ARCH}.tar.gz"
  TMP="$(mktemp -d)"
  curl -sL "$URL" | tar -xz -C "$TMP"
  install -m755 "$TMP/mediamtx" /usr/local/bin/mediamtx
  rm -rf "$TMP"
}

case "$DISTRO_ID" in
  ubuntu|debian|raspbian) install_apt ;;
  fedora|rhel|centos|rocky|almalinux) install_dnf ;;
  arch|manjaro|endeavouros) install_pacman ;;
  *)
    if [[ "$DISTRO_LIKE" == *"debian"* ]]; then install_apt
    elif [[ "$DISTRO_LIKE" == *"rhel"* || "$DISTRO_LIKE" == *"fedora"* ]]; then install_dnf
    elif [[ "$DISTRO_LIKE" == *"arch"* ]]; then install_pacman
    else err "Unsupported distro: $DISTRO_ID"; exit 1; fi
    ;;
esac

# ---------- Python venv ----------
PY="$(command -v python3)"
log "Creating venv with $PY (--system-site-packages to use distro PyGObject)"
"$PY" -m venv --system-site-packages backend/.venv
PIP="backend/.venv/bin/pip"
"$PIP" install -q --upgrade pip

if $RPI; then EXTRAS="[rpi,mcp,dev]"
elif $CORE_ONLY; then EXTRAS="[mcp,dev]"
else EXTRAS="[inference,thermal,mcp,dev]"; fi

log "Installing camera_dash$EXTRAS …"
"$PIP" install -q -e "backend$EXTRAS"

if ! $CORE_ONLY; then
  log "Installing optional ML extras (supervision, anthropic, depthai)…"
  "$PIP" install -q supervision anthropic depthai || warn "Some optional deps failed"
fi

# ---------- Frontend ----------
log "Installing frontend node deps…"
(cd frontend && npm install --silent --no-audit --no-fund)

# ---------- Optional: Kinect 360 (v1) ----------
if $WITH_KINECT; then
  log "Installing libfreenect + freenect Python wrapper for Kinect 360 support…"
  # install-kinect-v1.sh runs sudo as needed; drop privileges so the venv pip
  # call stays as the real user.
  REAL_USER="${SUDO_USER:-$USER}"
  if [[ -n "$REAL_USER" && "$REAL_USER" != "root" ]]; then
    sudo -u "$REAL_USER" bash scripts/install-kinect-v1.sh || warn "Kinect installer failed (continuing)"
  else
    bash scripts/install-kinect-v1.sh || warn "Kinect installer failed (continuing)"
  fi
fi

# ---------- Allow user access to /dev/video* ----------
if getent group video >/dev/null; then
  REAL_USER="${SUDO_USER:-$USER}"
  usermod -a -G video "$REAL_USER" || warn "Could not add $REAL_USER to video group"
  log "Added $REAL_USER to video group (re-login required for it to take effect)"
fi

cat <<EOF

$(printf '\033[1;32m✓ camera_dash installed.\033[0m')

To run, in three terminals:

  mediamtx mediamtx/mediamtx.yml
  ./scripts/run.sh backend
  ./scripts/run.sh frontend

Then open http://localhost:5173

Notes:
  • If you just got added to the video group, log out and back in.
  • For PiCamera / NVIDIA GPU / Coral, see docs/INSTALLATION.md.
  • Set ANTHROPIC_API_KEY for AI features.

EOF
