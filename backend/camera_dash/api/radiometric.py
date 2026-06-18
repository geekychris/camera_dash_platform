"""WebSocket: per-frame radiometric matrix for a FLIR camera.

The browser FlirOverlay subscribes; on mouse hover it reads the matrix and
displays Celsius at the cursor. We downsample to keep WS bandwidth modest.

Wire format (binary, little-endian, per message):
  uint16  width
  uint16  height
  uint16[w*h]  centi-Kelvin values
"""

from __future__ import annotations

import logging
import struct

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..pipeline.types import PixelFormat
from ..utils.radiometric import downsample_for_ws

log = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/{camera_id}")
async def radiometric_ws(ws: WebSocket, camera_id: str) -> None:
    await ws.accept()
    bus = ws.app.state.frame_bus
    q = await bus.subscribe(camera_id, depth=2)
    try:
        while True:
            frame = await q.get()
            if frame.pixel_format != PixelFormat.THERMAL14 or frame.radiometric is None:
                continue
            down = downsample_for_ws(frame.radiometric, max_dim=320)
            h, w = down.shape[:2]
            header = struct.pack("<HH", w, h)
            await ws.send_bytes(header + down.astype("<u2").tobytes())
    except WebSocketDisconnect:
        return
    except Exception:
        log.exception("radiometric ws error")
    finally:
        await bus.unsubscribe(camera_id, q)
