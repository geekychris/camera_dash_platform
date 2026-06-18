"""MediaMTX integration: health check + URL helpers.

We don't manage the MediaMTX process here; it's expected to be run separately
(docker-compose service or systemd). These helpers let the API report whether
MediaMTX is reachable and where the browser should connect for each camera.
"""

from __future__ import annotations

from typing import Any

import httpx


async def health(settings: Any, timeout: float = 1.0) -> dict[str, Any]:
    s = settings.streaming
    url = f"http://{s.mediamtx_host}:{s.mediamtx_api_port}/v3/paths/list"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
        r.raise_for_status()
        data = r.json()
        return {"ok": True, "paths": [p.get("name") for p in data.get("items", [])]}
    except Exception as exc:  # pragma: no cover - network
        return {"ok": False, "error": str(exc)}


def webrtc_url(settings: Any, camera_id: str) -> str:
    """WHEP endpoint the browser uses to pull WebRTC."""
    s = settings.streaming
    return f"http://{s.mediamtx_host}:{s.mediamtx_webrtc_port}/camera/{camera_id}/whep"


def hls_url(settings: Any, camera_id: str) -> str:
    s = settings.streaming
    # MediaMTX default HLS port is 8888
    return f"http://{s.mediamtx_host}:8888/camera/{camera_id}/index.m3u8"


def rtsp_url(settings: Any, camera_id: str) -> str:
    s = settings.streaming
    return f"rtsp://{s.mediamtx_host}:{s.mediamtx_rtsp_port}/camera/{camera_id}"
