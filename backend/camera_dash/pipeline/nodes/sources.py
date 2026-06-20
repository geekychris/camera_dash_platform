"""Source nodes — entry points into a pipeline. Override run() because they
have no inputs to read in a tick.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import cv2
import numpy as np

from ...pipeline.types import AudioFrame, Frame, PixelFormat
from ..node import Inbox, Node, Outbox, Port
from ..types import PortType

log = logging.getLogger(__name__)


class CameraSourceNode(Node):
    """Subscribes to a camera on the FrameBus and emits frames."""

    TYPE_ID = "source.camera"
    UI_CATEGORY = "source"
    INPUTS = ()
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["camera_id"],
        "properties": {
            "camera_id": {"type": "string", "title": "Camera ID"},
            "queue_depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 8},
        },
    }

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        camera_id = self.config["camera_id"]
        depth = int(self.config.get("queue_depth", 2))
        bus = self.context.frame_bus
        q = await bus.subscribe(camera_id, depth=depth)
        try:
            while True:
                frame = await q.get()
                await outbox.publish({"frame": frame})
        finally:
            await bus.unsubscribe(camera_id, q)


class CameraDepthSourceNode(Node):
    """Subscribes to the depth channel of a camera and emits ``DepthFrame``s.

    Only depth-capable cameras (Kinect, OAK-D with depth enabled, etc.)
    publish on this channel — for a UVC webcam the queue stays empty forever.
    Pair with ``source.camera`` if a pipeline needs both the color preview
    and aligned depth.
    """

    TYPE_ID = "source.camera_depth"
    UI_CATEGORY = "source"
    INPUTS = ()
    OUTPUTS = (Port("depth", PortType.DEPTH_FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["camera_id"],
        "properties": {
            "camera_id": {"type": "string", "title": "Camera ID",
                          "description": "Must be a depth-capable camera (kinect_v1, oak with depth)"},
            "queue_depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 8},
        },
    }

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        camera_id = self.config["camera_id"]
        depth = int(self.config.get("queue_depth", 2))
        bus = self.context.frame_bus
        q = await bus.subscribe_depth(camera_id, depth=depth)
        try:
            while True:
                df = await q.get()
                await outbox.publish({"depth": df})
        finally:
            await bus.unsubscribe_depth(camera_id, q)


class FileSourceNode(Node):
    """Reads frames from a video file (for testing pipelines without hardware)."""

    TYPE_ID = "source.file"
    UI_CATEGORY = "source"
    INPUTS = ()
    OUTPUTS = (Port("frame", PortType.FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string", "title": "Video file path"},
            "camera_id": {"type": "string", "default": "file", "title": "Reported camera_id"},
            "loop": {"type": "boolean", "default": True},
            "fps": {"type": "integer", "default": 30},
        },
    }

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        path = self.config["path"]
        camera_id = self.config.get("camera_id", "file")
        loop = bool(self.config.get("loop", True))
        target_fps = int(self.config.get("fps", 30))
        period = 1.0 / target_fps

        while True:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                raise RuntimeError(f"could not open video: {path}")
            try:
                while True:
                    ok, frame_bgr = await asyncio.to_thread(cap.read)
                    if not ok:
                        break
                    h, w = frame_bgr.shape[:2]
                    fr = Frame(
                        camera_id=camera_id, timestamp_ns=time.time_ns(),
                        width=w, height=h, pixel_format=PixelFormat.BGR, data=frame_bgr,
                    )
                    await outbox.publish({"frame": fr})
                    await asyncio.sleep(period)
            finally:
                cap.release()
            if not loop:
                return


class AudioSourceNode(Node):
    """Microphone source — capture PCM audio and publish as ``AudioFrame``.

    Uses ``sounddevice`` (PortAudio) so we don't have to fight with ALSA /
    PulseAudio / CoreAudio backends directly. Each chunk fires onto the
    FrameBus's audio channel under the configured ``camera_id`` (the channel
    is keyed by camera id so audio + video from the same physical camera
    share the routing key).

    Pairs with ``detector.audio_class`` (YAMNet) or any custom node that
    consumes ``PortType.AUDIO_FRAME``.

    Defaults to system default input, 16 kHz mono, 0.5 s chunks — matches
    the standard YAMNet input cadence.
    """

    TYPE_ID = "source.audio"
    UI_CATEGORY = "source"
    INPUTS = ()
    OUTPUTS = (Port("audio", PortType.AUDIO_FRAME),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "camera_id": {
                "type": "string", "default": "mic",
                "description": "Bus routing key; reuses camera_id so an audio source pairs with a video camera by id",
            },
            "device": {
                "type": ["integer", "string"], "default": -1,
                "description": "sounddevice device index or substring of name; -1 = default input",
            },
            "sample_rate": {"type": "integer", "default": 16000,
                              "description": "Hz — YAMNet expects 16000"},
            "chunk_ms": {"type": "integer", "default": 500, "minimum": 50, "maximum": 5000,
                          "description": "Chunk size in milliseconds. Smaller = lower latency."},
            "channels": {"type": "integer", "enum": [1, 2], "default": 1},
        },
    }

    async def run(self, inbox: Inbox, outbox: Outbox) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "source.audio needs `sounddevice` — install with `pip install sounddevice`. "
                "On Linux you also need libportaudio2 (apt install libportaudio2)."
            ) from exc

        camera_id = str(self.config.get("camera_id", "mic"))
        sample_rate = int(self.config.get("sample_rate", 16000))
        chunk_samples = int(sample_rate * int(self.config.get("chunk_ms", 500)) / 1000)
        channels = int(self.config.get("channels", 1))
        device: Any = self.config.get("device", -1)
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        if isinstance(device, int) and device < 0:
            device = None

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=16)

        def callback(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
            if status:
                log.warning("source.audio status: %s", status)
            mono = indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0]
            loop.call_soon_threadsafe(queue.put_nowait, mono.astype(np.float32).copy())

        stream = sd.InputStream(
            samplerate=sample_rate, channels=channels, dtype="float32",
            blocksize=chunk_samples, device=device, callback=callback,
        )
        try:
            stream.start()
            log.info("source.audio capturing on %s @ %d Hz, %d ms chunks (camera_id=%s)",
                     device if device is not None else "default", sample_rate,
                     int(self.config.get("chunk_ms", 500)), camera_id)
            while True:
                chunk = await queue.get()
                af = AudioFrame(
                    camera_id=camera_id, timestamp_ns=time.time_ns(),
                    sample_rate=sample_rate, data=chunk, channels=channels,
                )
                bus = self.context.frame_bus
                if bus is not None:
                    bus.publish_audio_nowait(camera_id, af)
                await outbox.publish({"audio": af})
        finally:
            stream.stop()
            stream.close()
