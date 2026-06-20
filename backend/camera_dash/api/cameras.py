"""Cameras REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..cameras.base import CameraSpec
from ..streaming.mediamtx import hls_url, rtsp_url, webrtc_url

router = APIRouter()


class CameraIn(BaseModel):
    id: str
    kind: str = Field(..., description="uvc | flir_lepton")
    label: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class CameraOut(BaseModel):
    id: str
    kind: str
    label: str
    params: dict[str, Any]
    running: bool
    is_thermal: bool
    has_depth: bool = False
    urls: dict[str, str]


def _enrich(info: dict[str, Any], request: Request) -> CameraOut:
    settings = request.app.state.settings
    info = dict(info)
    info["urls"] = {
        "webrtc": webrtc_url(settings, info["id"]),
        "hls": hls_url(settings, info["id"]),
        "rtsp": rtsp_url(settings, info["id"]),
    }
    return CameraOut(**info)


@router.get("", response_model=list[CameraOut])
async def list_cameras(request: Request) -> list[CameraOut]:
    mgr = request.app.state.camera_manager
    return [_enrich(c, request) for c in mgr.list()]


@router.get("/discover")
async def discover(request: Request) -> dict[str, Any]:
    """List devices the host can see, grouped by driver.

    Returns ``uvc`` (GStreamer DeviceMonitor — covers UVC webcams, FLIR
    PureThermal, iPhone Continuity) and ``kinect`` (libfreenect device count).
    """
    mgr = request.app.state.camera_manager
    return {
        "uvc": mgr.discover(),
        "kinect": mgr.discover_kinects(),
    }


@router.post("", response_model=CameraOut, status_code=201)
async def add_camera(payload: CameraIn, request: Request) -> CameraOut:
    mgr = request.app.state.camera_manager
    streaming = request.app.state.streaming
    spec = CameraSpec(id=payload.id, kind=payload.kind, label=payload.label,
                      params=payload.params, enabled=payload.enabled)
    try:
        cam = await mgr.add(spec)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    if payload.enabled:
        # Some kinds (kinect_v1, flir_lepton) pin their resolution from the
        # device, so prefer the camera-reported params over the request body.
        actual_params = cam.info().get("params", payload.params)
        w = int(actual_params.get("width", payload.params.get("width", 1280)))
        h = int(actual_params.get("height", payload.params.get("height", 720)))
        fps = int(actual_params.get("fps", payload.params.get("fps", 30)))
        await streaming.attach(cam.id, w, h, fps)
    return _enrich(cam.info(), request)


@router.delete("/{camera_id}", status_code=204)
async def remove_camera(camera_id: str, request: Request) -> None:
    mgr = request.app.state.camera_manager
    streaming = request.app.state.streaming
    await streaming.detach(camera_id)
    await mgr.remove(camera_id)


class LabelPatch(BaseModel):
    label: str


@router.patch("/{camera_id}", response_model=CameraOut)
async def update_label(camera_id: str, payload: LabelPatch, request: Request) -> CameraOut:
    mgr = request.app.state.camera_manager
    try:
        await mgr.update_label(camera_id, payload.label)
    except KeyError as exc:
        raise HTTPException(404, "camera not found") from exc
    cam = mgr.get(camera_id)
    assert cam is not None
    return _enrich(cam.info(), request)


@router.post("/{camera_id}/restream", response_model=CameraOut)
async def restream(camera_id: str, request: Request) -> CameraOut:
    """Tear down and recreate the GStreamer publisher for one camera.

    Useful when rtspclientsink loses its connection to MediaMTX (e.g. after a
    relay restart) without affecting other cameras or the capture loop.
    """
    mgr = request.app.state.camera_manager
    streaming = request.app.state.streaming
    cam = mgr.get(camera_id)
    if cam is None:
        raise HTTPException(404, "camera not found")
    await streaming.detach(camera_id)
    info = cam.info()
    params = info.get("params", {})
    w = int(params.get("width", 1280))
    h = int(params.get("height", 720))
    fps = int(params.get("fps", 30))
    await streaming.attach(camera_id, w, h, fps)
    return _enrich(info, request)


@router.post("/{camera_id}/restart", response_model=CameraOut)
async def restart_camera(camera_id: str, request: Request) -> CameraOut:
    """Stop and restart a single camera in-place.

    Goes deeper than ``/restream``: stops the capture loop, tears down the
    driver, and re-creates it from the same spec. Use this after a hardware
    replug (Kinect/FLIR coming back on the bus) so the driver gets a fresh
    device handle without bouncing the whole backend.

    The camera spec is preserved (not re-persisted); other cameras and
    pipelines keep running untouched.
    """
    mgr = request.app.state.camera_manager
    streaming = request.app.state.streaming
    cam = mgr.get(camera_id)
    if cam is None:
        raise HTTPException(404, "camera not found")
    # Snapshot the spec so we can recreate after we drop the camera.
    spec = cam.spec
    try:
        await streaming.detach(camera_id)
        await mgr.remove(camera_id, persist=False)
        new_cam = await mgr.add(spec, persist=False)
    except Exception as exc:  # pragma: no cover - bubble up the failure cause
        raise HTTPException(500, f"restart failed: {exc}") from exc
    info = new_cam.info()
    params = info.get("params", {})
    w = int(params.get("width", 1280))
    h = int(params.get("height", 720))
    fps = int(params.get("fps", 30))
    await streaming.attach(camera_id, w, h, fps)
    return _enrich(info, request)
