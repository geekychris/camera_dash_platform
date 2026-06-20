"""``sink.jsonl`` — append events as newline-delimited JSON.

The default destination is ``data/events/<pipeline_id>.jsonl`` so multiple
pipelines don't trample each other. Each line is a JSON object with
``timestamp``, ``pipeline_id``, ``node_id``, ``camera_id``, ``kind``, ``payload``.

JSONL (a.k.a. NDJSON) is the universal data-engineering append format:
``jq``, ``duckdb``, ``pandas.read_json(..., lines=True)`` and most log
ingesters can consume it directly. Use it as a cheap audit log, a replay
source for offline analysis, or as input to a downstream stream processor.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ....pipeline.types import Event, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)


def _default_event_encoder(o: Any) -> Any:
    if hasattr(o, "isoformat"):
        return o.isoformat()
    try:
        import numpy as np  # type: ignore
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
    except ImportError:
        pass
    return str(o)


class JsonlSink(Node):
    TYPE_ID = "sink.jsonl"
    UI_CATEGORY = "sink"
    INPUTS = (Port("payload", PortType.EVENT),)
    OUTPUTS = ()
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string", "default": "",
                "description": "Output file. Empty = data/events/<pipeline_id>.jsonl. "
                                "Parent directories are created automatically.",
            },
            "rotate_mb": {
                "type": "number", "default": 0, "minimum": 0,
                "description": "Rotate file when it exceeds this many MB. 0 = never rotate.",
            },
            "max_files": {
                "type": "integer", "default": 5, "minimum": 1, "maximum": 1000,
                "description": "Keep this many rotated files before deleting the oldest.",
            },
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._path: Path | None = None
        self._lock = asyncio.Lock()

    async def setup(self) -> None:
        cfg_path = str(self.config.get("path") or "")
        if not cfg_path:
            cfg_path = f"data/events/{self.context.pipeline_id}.jsonl"
        self._path = Path(cfg_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def process(self, **inputs: Any) -> dict[str, Any]:
        evt: Event | None = inputs.get("payload")
        if evt is None or self._path is None:
            return {}
        row = {
            "timestamp": datetime.now(UTC).isoformat(),
            "pipeline_id": evt.pipeline_id,
            "node_id": evt.node_id,
            "camera_id": evt.camera_id,
            "kind": evt.kind,
            "event_ts_ns": evt.timestamp_ns,
            "payload": evt.payload,
        }
        line = json.dumps(row, default=_default_event_encoder, separators=(",", ":")) + "\n"
        async with self._lock:
            await asyncio.to_thread(self._append_and_maybe_rotate, line)
        return {}

    def _append_and_maybe_rotate(self, line: str) -> None:
        assert self._path is not None
        rotate_mb = float(self.config.get("rotate_mb", 0))
        if rotate_mb > 0 and self._path.exists():
            size_mb = self._path.stat().st_size / (1024 * 1024)
            if size_mb >= rotate_mb:
                self._rotate()
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)

    def _rotate(self) -> None:
        assert self._path is not None
        max_files = int(self.config.get("max_files", 5))
        # Find existing rotations and shift them up; drop the oldest.
        base = self._path
        for i in range(max_files - 1, 0, -1):
            old = base.with_suffix(base.suffix + f".{i}")
            new = base.with_suffix(base.suffix + f".{i + 1}")
            if old.exists():
                if new.exists():
                    new.unlink()
                old.rename(new)
        base.rename(base.with_suffix(base.suffix + ".1"))
