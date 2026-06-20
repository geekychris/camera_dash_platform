"""WebSocket: per-frame depth matrix (mm) for a depth-capable camera.

The browser KinectDepthOverlay subscribes; on mouse hover it reads the matrix
and displays the distance at the cursor. Downsampled to keep WS bandwidth
modest.

Wire format (binary, little-endian, per message):
  uint16  width
  uint16  height
  uint16[w*h]  millimetres; 0 means "no reading" (out-of-range, IR shadow)
"""

from __future__ import annotations

import logging
import struct

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

router = APIRouter()


def _downsample(matrix, max_dim: int = 320):
    """Reduce matrix to ~max_dim on the longest side; preserves uint16."""
    import cv2

    h, w = matrix.shape[:2]
    if max(h, w) <= max_dim:
        return matrix
    scale = max_dim / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    # INTER_NEAREST preserves 0=invalid sentinels instead of smearing them into
    # spurious mid-range averages.
    return cv2.resize(matrix, (new_w, new_h), interpolation=cv2.INTER_NEAREST)


@router.websocket("/{camera_id}")
async def depth_ws(ws: WebSocket, camera_id: str) -> None:
    await ws.accept()
    bus = ws.app.state.frame_bus
    q = await bus.subscribe_depth(camera_id, depth=2)
    try:
        while True:
            df = await q.get()
            down = _downsample(df.data, max_dim=320)
            h, w = down.shape[:2]
            header = struct.pack("<HH", w, h)
            await ws.send_bytes(header + down.astype("<u2").tobytes())
    except WebSocketDisconnect:
        return
    except Exception:
        log.exception("depth ws error")
    finally:
        await bus.unsubscribe_depth(camera_id, q)
