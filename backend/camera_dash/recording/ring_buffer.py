"""Rolling per-camera ring buffer for pre-roll recording.

Implementation: one always-on ffmpeg per camera that pulls from MediaMTX RTSP
and writes segmented mp4 files (``segment_time=2s``, wrapped to N files). When
a trigger fires, the recorder concatenates the last K segments + a fresh
post-roll capture into the final clip.

Per camera storage: ~ ``capacity_s * bitrate`` bytes (default 60s = ~15MB at
2 Mbit/s). The buffer directory is created under ``data/clips/.buffer/<cam>/``.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

SEG_SECONDS = 2  # length of each segment file


class RingBuffer:
    """Always-on segmented recorder for one camera.

    Use :meth:`segment_paths` to enumerate currently-present segments, oldest
    first. Use :meth:`segments_covering` to grab the segments needed to
    reconstruct the last N seconds before a trigger.
    """

    def __init__(self, camera_id: str, source_url: str, capacity_s: int,
                 directory: Path) -> None:
        self.camera_id = camera_id
        self.source_url = source_url
        self.capacity_s = capacity_s
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg not found on PATH")
        wrap = max(2, (self.capacity_s + SEG_SECONDS - 1) // SEG_SECONDS + 1)
        pattern = str(self.directory / "seg_%05d.ts")
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-rtsp_transport", "tcp", "-i", self.source_url,
            "-c", "copy",
            "-f", "segment", "-segment_time", str(SEG_SECONDS),
            "-segment_wrap", str(wrap),
            "-reset_timestamps", "1",
            pattern,
        ]
        log.info("ring buffer %s starting (wrap=%d, capacity=%ds)",
                 self.camera_id, wrap, self.capacity_s)
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        self._running = True
        self._task = asyncio.create_task(self._reaper(), name=f"ring/{self.camera_id}")

    async def _reaper(self) -> None:
        assert self._proc is not None
        try:
            rc = await self._proc.wait()
            if self._running:
                log.warning("ring buffer %s ffmpeg exited rc=%s", self.camera_id, rc)
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._proc is not None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except (TimeoutError, ProcessLookupError):
                import contextlib
                with contextlib.suppress(ProcessLookupError):
                    self._proc.kill()
            self._proc = None
        if self._task is not None:
            self._task.cancel()
            import contextlib
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        log.info("ring buffer %s stopped", self.camera_id)

    def segment_paths(self) -> list[Path]:
        files = sorted(self.directory.glob("seg_*.ts"), key=lambda p: p.stat().st_mtime)
        return files

    def segments_covering(self, seconds: int) -> list[Path]:
        n = max(1, (seconds + SEG_SECONDS - 1) // SEG_SECONDS)
        return self.segment_paths()[-n:]


class RingBufferManager:
    """One ring buffer per camera, shared across pipelines."""

    def __init__(self, settings: object, clips_dir: Path) -> None:
        self.settings = settings
        self.clips_dir = clips_dir
        self._buffers: dict[str, RingBuffer] = {}
        self._refcount: dict[str, int] = {}

    async def acquire(self, camera_id: str, capacity_s: int,
                       source_url: str) -> RingBuffer:
        buf = self._buffers.get(camera_id)
        if buf is None:
            buf_dir = self.clips_dir / ".buffer" / camera_id
            buf = RingBuffer(camera_id, source_url, capacity_s, buf_dir)
            await buf.start()
            self._buffers[camera_id] = buf
        self._refcount[camera_id] = self._refcount.get(camera_id, 0) + 1
        # Expand capacity if a new requester needs more
        if buf.capacity_s < capacity_s:
            buf.capacity_s = capacity_s
        return buf

    async def release(self, camera_id: str) -> None:
        self._refcount[camera_id] = max(0, self._refcount.get(camera_id, 0) - 1)
        if self._refcount[camera_id] == 0:
            buf = self._buffers.pop(camera_id, None)
            if buf:
                await buf.stop()

    async def stop_all(self) -> None:
        await asyncio.gather(*(b.stop() for b in self._buffers.values()),
                              return_exceptions=True)
        self._buffers.clear()
        self._refcount.clear()
