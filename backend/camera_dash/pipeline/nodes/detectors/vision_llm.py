"""Vision-LLM describer — call Claude on a frame for a rich text description.

YOLO tells you ``person, n=1``. Claude can tell you "a person in a red jacket
holding a bag, standing near the doorway". Use this for alert messages that a
human actually wants to read, not just count.

To save tokens this node throttles: it sends at most one request per
``min_interval_s`` seconds (default 30). For event-driven use, wire it after a
condition node so it only fires when something interesting happens.

Inputs:
    frame              the image to describe
    trigger (optional) if connected, only call the LLM when this fires

Outputs:
    event              an :class:`Event` with the model's text description
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from typing import Any, ClassVar

from ....pipeline.types import Event, Frame, PortType
from ...node import Inbox, Node, Outbox, Port

log = logging.getLogger(__name__)


class VisionLlmNode(Node):
    TYPE_ID = "detector.vision_llm"
    UI_CATEGORY = "detector"
    INPUTS = (
        Port("frame", PortType.FRAME),
        Port("trigger", PortType.EVENT, required=False),
    )
    OUTPUTS = (Port("event", PortType.EVENT),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "model": {"type": "string", "default": "claude-haiku-4-5",
                       "description": "Claude model id; haiku is fast+cheap, sonnet is more capable"},
            "prompt": {"type": "string",
                        "default": "Describe what you see in 1-2 sentences. Focus on people, "
                                   "animals, vehicles, and any unusual or notable activity.",
                        "description": "User prompt sent alongside the image"},
            "min_interval_s": {"type": "number", "default": 30.0,
                                "description": "Throttle: min seconds between calls"},
            "max_tokens": {"type": "integer", "default": 200},
            "api_key_env": {"type": "string", "default": "ANTHROPIC_API_KEY"},
            "trigger_only": {"type": "boolean", "default": True,
                              "description": "If true, only fire when the trigger input receives an Event"},
            "jpeg_quality": {"type": "integer", "default": 70,
                              "description": "JPEG compression quality before base64-encoding the frame"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._client: Any = None
        self._last_call: float = 0.0

    async def setup(self) -> None:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "vision_llm requires the anthropic SDK: pip install anthropic"
            ) from exc
        env = self.config.get("api_key_env", "ANTHROPIC_API_KEY")
        if not os.environ.get(env):
            raise RuntimeError(f"vision_llm needs ${env} set with your Anthropic API key")
        self._client = anthropic.AsyncAnthropic()

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        trigger_only = bool(self.config.get("trigger_only", True))
        while True:
            inputs = await inbox.read_all()
            if inputs is None:
                return
            frame: Frame | None = inputs.get("frame")
            trigger: Event | None = inputs.get("trigger")
            if frame is None:
                continue
            if trigger_only and trigger is None:
                continue
            # Throttle
            now = time.monotonic()
            min_interval = float(self.config.get("min_interval_s", 30.0))
            if (now - self._last_call) < min_interval:
                continue
            self._last_call = now
            t = asyncio.create_task(self._describe_and_emit(frame, outbox),
                                     name=f"vision_llm/{self.node_id}")
            VisionLlmNode._pending.add(t)
            t.add_done_callback(VisionLlmNode._pending.discard)

    _pending: ClassVar[set[asyncio.Task[Any]]] = set()

    async def _describe_and_emit(self, frame: Frame, outbox: Outbox) -> None:
        try:
            description = await self._call_claude(frame)
        except Exception:
            log.exception("vision_llm call failed")
            return
        evt = Event(
            pipeline_id=self.context.pipeline_id, node_id=self.node_id,
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            kind="vision_description",
            payload={"description": description, "model": self.config.get("model")},
        )
        await outbox.publish({"event": evt})
        if self.context.event_bus is not None:
            self.context.event_bus.publish_nowait(evt)

    async def _call_claude(self, frame: Frame) -> str:
        import cv2

        quality = int(self.config.get("jpeg_quality", 70))
        ok, encoded = await asyncio.to_thread(
            cv2.imencode, ".jpg", frame.data, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise RuntimeError("jpeg encode failed")
        b64 = base64.b64encode(encoded.tobytes()).decode("ascii")
        msg = await self._client.messages.create(
            model=self.config.get("model", "claude-haiku-4-5"),
            max_tokens=int(self.config.get("max_tokens", 200)),
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": self.config.get("prompt",
                                                              "Describe what you see in 1-2 sentences.")},
                ],
            }],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
