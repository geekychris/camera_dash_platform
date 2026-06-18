#!/usr/bin/env bash
# Enable Lepton radiometric (TLinear) mode on the PureThermal FLIR.
#
# Sequence: stop the FLIR camera in camera_dash (releases AVFoundation's UVC
# claim), send the Lepton XU commands via libuvc, re-add the camera so it
# starts streaming again with TLinear output, then probe to verify.
#
# Usage:
#   sudo ./scripts/enable-flir-radiometric.sh           # uses defaults below
#   sudo CAMERA_DASH_API=http://localhost:8001 ./scripts/enable-flir-radiometric.sh
#
# Why sudo: on macOS the kernel UVC driver (via VDCAssistant) auto-claims
# class-compliant UVC devices. Without root, libuvc cannot override the
# claim and uvc_open returns -3 (UVC_ERROR_ACCESS).

set -euo pipefail

API="${CAMERA_DASH_API:-http://localhost:8001}"
CAM_ID="${FLIR_CAM_ID:-flir}"
CAM_DEVICE_NAME="${FLIR_DEVICE_NAME:-PureThermal (fw:v1.0.0)}"
CAM_WIDTH="${FLIR_WIDTH:-160}"
CAM_HEIGHT="${FLIR_HEIGHT:-120}"
CAM_FPS="${FLIR_FPS:-9}"

# Resolve repo root from this script's location
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${REPO_ROOT}/backend/.venv/bin/python"
RADIO_SCRIPT="${REPO_ROOT}/scripts/flir_radiometric.py"

if [[ ! -x "$PYTHON" ]]; then
  echo "no venv python at $PYTHON — run scripts/dev-setup.sh first" >&2
  exit 1
fi
if [[ ! -f "$RADIO_SCRIPT" ]]; then
  echo "missing $RADIO_SCRIPT" >&2
  exit 1
fi

if [[ "$(uname)" == "Darwin" && "$EUID" -ne 0 ]]; then
  cat >&2 <<EOF
On macOS this needs root to override the kernel UVC driver claim.
Re-run with:
  sudo $0
EOF
  exit 1
fi

step() { printf "\n\033[1;36m▸ %s\033[0m\n" "$*"; }

step "1/4  stop the FLIR camera (releases AVFoundation's USB claim)"
http_status=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$API/api/cameras/$CAM_ID" || true)
echo "    DELETE /api/cameras/$CAM_ID -> $http_status"
if [[ "$http_status" != "204" && "$http_status" != "404" ]]; then
  echo "warning: unexpected status; continuing anyway" >&2
fi

# Give the macOS UVC driver time to fully relinquish the device. Without
# this, uvc_open often still returns -3 immediately after the camera stops.
echo "    waiting 6s for kernel driver to release the interface…"
sleep 6

step "2/4  send Lepton XU commands via libuvc"
if ! "$PYTHON" "$RADIO_SCRIPT"; then
  echo
  echo "✗ XU command failed. Re-adding the camera so you're not left without a feed."
  curl -s -X POST "$API/api/cameras" \
    -H "content-type: application/json" \
    -d "$(printf '{"id":"%s","kind":"flir_lepton","label":"FLIR Lepton","params":{"device_name":"%s","width":%s,"height":%s,"fps":%s},"enabled":true}' \
          "$CAM_ID" "$CAM_DEVICE_NAME" "$CAM_WIDTH" "$CAM_HEIGHT" "$CAM_FPS")" \
    -o /dev/null -w "    POST /api/cameras -> %{http_code}\n"
  exit 2
fi

step "3/4  re-add the FLIR camera in camera_dash"
http_status=$(curl -s -X POST "$API/api/cameras" \
  -H "content-type: application/json" \
  -d "$(printf '{"id":"%s","kind":"flir_lepton","label":"FLIR Lepton","params":{"device_name":"%s","width":%s,"height":%s,"fps":%s},"enabled":true}' \
        "$CAM_ID" "$CAM_DEVICE_NAME" "$CAM_WIDTH" "$CAM_HEIGHT" "$CAM_FPS")" \
  -o /dev/null -w "%{http_code}")
echo "    POST /api/cameras -> $http_status"
if [[ "$http_status" != "201" ]]; then
  echo "warning: re-add returned $http_status; check the backend log" >&2
fi

echo "    waiting 5s for the stream to come up…"
sleep 5

step "4/4  probe one frame to confirm the raw range is radiometric"
"$PYTHON" - <<'PY'
import asyncio, struct
import websockets


async def main() -> None:
    uri = "ws://localhost:8001/api/radiometric/flir"
    async with websockets.connect(uri) as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
        w, h = struct.unpack_from("<HH", msg, 0)
        data = struct.unpack_from(f"<{w*h}H", msg, 4)
        srt = sorted(data)
        n = len(srt)
        def p(q): return srt[int(q * (n - 1))]

        rng = (srt[0], p(0.5), srt[-1])
        ck = lambda r: r / 100 - 273.15
        f = lambda c: c * 9 / 5 + 32
        print(f"    frame {w}x{h}: raw min={rng[0]} med={rng[1]} max={rng[2]}")
        print(f"    centi-K interpretation: "
              f"{ck(rng[0]):+.1f}°C/{f(ck(rng[0])):+.1f}°F .. "
              f"{ck(rng[1]):+.1f}°C/{f(ck(rng[1])):+.1f}°F .. "
              f"{ck(rng[2]):+.1f}°C/{f(ck(rng[2])):+.1f}°F")

        # Heuristic: a real-world radiometric scene clusters in ~28000-35000 centi-K
        # (5°C..77°C). A median outside that almost certainly means the camera
        # is still in AGC mode.
        if 28000 <= rng[1] <= 35000:
            print("    ✓ median is in a plausible radiometric range")
        else:
            print("    ⚠ median is OUTSIDE typical radiometric range — camera may still be in AGC")


asyncio.run(main())
PY

echo
echo "▸ done. Refresh the dashboard; hovering should now read sensible °F."
