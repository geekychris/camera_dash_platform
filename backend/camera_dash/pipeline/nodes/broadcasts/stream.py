"""``broadcast.stream`` — re-publish processed frames as a derived video stream.

Drop one at the tail of a ``transform.annotate`` (or any frame-producing node)
to surface that node's output in the dashboard alongside the raw camera tiles.

In the node taxonomy this is a **broadcast**, not a sink: the data doesn't
leave the platform — it gets re-published over a different transport
(MediaMTX → WebRTC/HLS/RTSP) for many in-platform consumers. Compare to a
true sink like ``sink.mqtt`` which terminates the pipeline by emitting bytes
to an external system.

Mechanism: each incoming :class:`Frame` is re-published to the :class:`FrameBus`
under a derived id (``derived/<pipeline>/<node>``) and the same camera-streaming
publisher path (GStreamer ``appsrc`` → H.264 → RTSP push to MediaMTX) is
attached. The dashboard fetches the registry via ``/api/streams``.

Was historically registered as ``sink.stream``; the legacy TYPE_ID is still
accepted by the catalog loader for back-compat with saved pipelines.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ....pipeline.types import Frame, PortType
from ....streaming.registry import DerivedStream
from ...node import Inbox, Node, Outbox, Port

log = logging.getLogger(__name__)


class StreamBroadcast(Node):
    TYPE_ID = "broadcast.stream"
    UI_CATEGORY = "broadcast"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "default": "",
                       "description": "Display name in the dashboard; defaults to <pipeline>/<node>"},
            "fps": {"type": "integer", "default": 15,
                     "description": "Encoder target FPS for the derived stream"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._stream_id: str = ""
        self._registered = False
        self._dims: tuple[int, int] | None = None  # (w, h) — set on first frame
        self._attach_task: asyncio.Task[None] | None = None

    async def setup(self) -> None:
        self._stream_id = f"derived/{self.context.pipeline_id}/{self.node_id}"

    async def teardown(self) -> None:
        streaming = self.context.streaming
        registry = self.context.derived_streams
        if streaming is not None:
            await streaming.detach(self._stream_id)
        if registry is not None:
            await registry.remove(self._stream_id)
        if self._attach_task is not None and not self._attach_task.done():
            self._attach_task.cancel()

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            frame: Frame | None = inputs.get("frame")
            if frame is None:
                continue
            if self._dims is None:
                self._dims = (frame.width, frame.height)
                self._attach_task = asyncio.create_task(
                    self._first_frame_setup(frame),
                    name=f"broadcast.stream/{self._stream_id}/attach",
                )
            self.context.frame_bus.publish_nowait(self._stream_id, frame)

    async def _first_frame_setup(self, frame: Frame) -> None:
        streaming = self.context.streaming
        registry = self.context.derived_streams
        fps = int(self.config.get("fps", 15))
        label = self.config.get("label") or f"{self.context.pipeline_id}/{self.node_id}"
        if streaming is not None:
            try:
                await streaming.attach(self._stream_id, frame.width, frame.height, fps)
            except Exception:
                log.exception("failed to attach derived stream %s", self._stream_id)
        if registry is not None and not self._registered:
            await registry.add(DerivedStream(
                id=self._stream_id,
                pipeline_id=self.context.pipeline_id,
                node_id=self.node_id,
                label=label,
                source_camera_id=frame.camera_id,
                width=frame.width,
                height=frame.height,
                fps=fps,
            ))
            self._registered = True
        log.info("derived stream %s registered (%dx%d @ %dfps)",
                 self._stream_id, frame.width, frame.height, fps)
