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


def _host(settings: Any, override: str | None) -> str:
    """Pick the right host for browser-facing URLs.

    When the dashboard is hit over the LAN (e.g. `http://pi5-8.local:5173/`),
    the configured `mediamtx_host` (often `127.0.0.1`) is wrong — the
    browser running on the Mac would resolve `127.0.0.1` to itself. The
    request handler derives the dashboard-visible host from `Host` /
    `X-Forwarded-Host` and passes it here so URLs come back pointing at
    the actual server. If no override is given, fall back to the
    configured host (still useful for non-HTTP callers like the docs).
    """
    if override:
        return override
    return settings.streaming.mediamtx_host


def webrtc_url(settings: Any, camera_id: str, host: str | None = None) -> str:
    """WHEP endpoint the browser uses to pull WebRTC."""
    s = settings.streaming
    return f"http://{_host(settings, host)}:{s.mediamtx_webrtc_port}/camera/{camera_id}/whep"


def hls_url(settings: Any, camera_id: str, host: str | None = None) -> str:
    s = settings.streaming
    # MediaMTX default HLS port is 8888
    return f"http://{_host(settings, host)}:8888/camera/{camera_id}/index.m3u8"


def rtsp_url(settings: Any, camera_id: str, host: str | None = None) -> str:
    s = settings.streaming
    return f"rtsp://{_host(settings, host)}:{s.mediamtx_rtsp_port}/camera/{camera_id}"
