"""Clip recorder sink.

Triggered by an Event on the ``trigger`` port. Pulls from the camera's RTSP
stream (via MediaMTX) using ffmpeg and writes an mp4 with ``pre_roll_s`` +
``post_roll_s`` duration. Pre-roll is best-effort: requires the
:class:`RingBuffer` in :mod:`camera_dash.recording.ring_buffer` to be running for
the camera; otherwise we only get post-roll.

Each clip is persisted as a row in the ``clips`` table for the API to enumerate.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from ....pipeline.types import Event, PortType
from ....recording.writer import write_clip
from ....storage import models
from ....storage.db import get_session
from ....streaming.mediamtx import rtsp_url
from ...node import Inbox, Node, Outbox, Port

log = logging.getLogger(__name__)


class RecorderSink(Node):
    TYPE_ID = "sink.recorder"
    UI_CATEGORY = "sink"
    INPUTS = (Port("trigger", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "camera_id": {"type": "string", "default": "",
                          "description": "Override; defaults to event.camera_id"},
            "pre_roll_s": {"type": "integer", "default": 5},
            "post_roll_s": {"type": "integer", "default": 25},
            "container": {"type": "string", "enum": ["mp4", "mkv"], "default": "mp4"},
            "cooldown_s": {"type": "integer", "default": 30,
                           "description": "Min seconds between clips per camera"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._last_record: dict[str, float] = {}

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            trigger: Event | None = inputs.get("trigger")
            if trigger is None:
                continue
            camera_id = self.config.get("camera_id") or trigger.camera_id
            if not camera_id:
                log.warning("recorder %s got trigger with no camera_id", self.node_id)
                continue
            cooldown = int(self.config.get("cooldown_s", 30))
            now = asyncio.get_running_loop().time()
            last = self._last_record.get(camera_id, 0.0)
            if now - last < cooldown:
                continue
            self._last_record[camera_id] = now
            self._fire_and_forget(self._record(camera_id, trigger), name=f"recorder/{self.node_id}/{camera_id}")

    _pending: ClassVar[set[asyncio.Task[Any]]] = set()

    @classmethod
    def _fire_and_forget(cls, coro, *, name: str) -> None:
        t = asyncio.create_task(coro, name=name)
        cls._pending.add(t)
        t.add_done_callback(cls._pending.discard)

    async def _record(self, camera_id: str, trigger: Event) -> None:
        settings = self.context.settings
        out_dir = Path(settings.storage.clips_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        clip_id = uuid.uuid4().hex
        ext = self.config.get("container", "mp4")
        path = out_dir / f"{camera_id}_{clip_id}.{ext}"

        source_url = rtsp_url(settings, camera_id)
        pre_roll = int(self.config.get("pre_roll_s", 5))
        post_roll = int(self.config.get("post_roll_s", 25))

        # Use the shared RingBufferManager so multiple recorder nodes share one
        # always-on background recorder per camera.
        ring_mgr = getattr(self.context, "ring_buffers", None)
        ring_buf = None
        if ring_mgr is not None and pre_roll > 0:
            try:
                ring_buf = await ring_mgr.acquire(camera_id, pre_roll + 2, source_url)
            except Exception:
                log.exception("ring buffer acquire failed for %s", camera_id)

        started = datetime.now(UTC)
        try:
            await write_clip(
                camera_id=camera_id, source_url=source_url, out_path=path,
                pre_roll_s=pre_roll, post_roll_s=post_roll,
                ring_buffer=ring_buf,
            )
        except Exception:
            log.exception("clip write failed for %s", camera_id)
            return
        ended = datetime.now(UTC)

        async with get_session() as s:
            s.add(models.Clip(
                id=clip_id, camera_id=camera_id,
                pipeline_id=trigger.pipeline_id, started_at=started, ended_at=ended,
                path=str(path),
                trigger={"node_id": trigger.node_id, "kind": trigger.kind,
                         "payload": trigger.payload},
            ))
            await s.commit()
        log.info("clip recorded: %s", path)
