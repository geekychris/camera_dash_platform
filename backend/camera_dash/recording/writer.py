"""Clip writer — combines pre-roll (from :class:`RingBuffer`) with post-roll
captured live, plus a thumbnail JPEG.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


async def write_clip(camera_id: str, source_url: str, out_path: Path,
                      pre_roll_s: int, post_roll_s: int,
                      ring_buffer: object | None = None) -> Path | None:
    """Write a clip and return the thumbnail path (or None on failure)."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pre_files: list[Path] = []
    if pre_roll_s > 0 and ring_buffer is not None:
        from .ring_buffer import RingBuffer  # type: ignore

        if isinstance(ring_buffer, RingBuffer):
            pre_files = ring_buffer.segments_covering(pre_roll_s)

    post_tmp = None
    if post_roll_s > 0:
        post_tmp = Path(tempfile.mkstemp(suffix=".ts", prefix="post_")[1])
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
            "-rtsp_transport", "tcp", "-i", source_url,
            "-t", str(post_roll_s), "-c", "copy", "-f", "mpegts",
            str(post_tmp),
        ]
        log.info("recording %s post-roll %ds -> %s", source_url, post_roll_s, post_tmp)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode != 0:
            log.error("ffmpeg post-roll failed for %s: %s",
                      camera_id, err.decode(errors="ignore")[-400:])
            post_tmp = None

    parts: list[Path] = list(pre_files)
    if post_tmp is not None and post_tmp.exists() and post_tmp.stat().st_size > 0:
        parts.append(post_tmp)
    if not parts:
        log.error("no segments to concat for %s", camera_id)
        return None

    # Concat via ffmpeg's concat demuxer (works for matched-codec .ts files)
    listfile = Path(tempfile.mkstemp(suffix=".txt", prefix="concat_")[1])
    listfile.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts))
    concat_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c", "copy", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *concat_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    listfile.unlink(missing_ok=True)
    if post_tmp is not None:
        post_tmp.unlink(missing_ok=True)
    if proc.returncode != 0:
        log.error("concat failed for %s: %s", camera_id, err.decode(errors="ignore")[-400:])
        return None

    # Thumbnail
    thumb_path = out_path.with_suffix(".jpg")
    thumb_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(out_path), "-ss", "00:00:01", "-vframes", "1",
        "-vf", "scale=320:-1", str(thumb_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *thumb_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await proc.wait()
    return thumb_path if thumb_path.exists() else None
