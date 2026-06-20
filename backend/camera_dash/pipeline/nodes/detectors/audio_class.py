"""Audio event classifier — runs YAMNet (TF Hub) on incoming audio chunks.

YAMNet is a CNN trained on Google's AudioSet (521 classes covering everything
from "glass breaking" and "dog bark" to "smoke alarm", "crying baby", "car
honk", "speech", "music"). Designed to chew 0.96 s of 16 kHz mono audio and
emit a 521-d score vector. We buffer incoming ``AudioFrame``s into a rolling
0.96 s window, run inference on the worker thread, and emit one
:class:`Detection` per class whose score exceeds ``min_score``.

Detections use ``label=<class name>`` and ``bbox=(0, 0, 0, 0)`` — audio has
no spatial extent. ``attrs["window_start_ns"]`` records when the window
began so downstream conditions can debounce on time, not on chunk count.

Install:
    pip install tensorflow-cpu tensorflow_hub      # full TF
or:
    pip install tflite-runtime                     # YAMNet has a .tflite path
                                                    # but it needs slightly different
                                                    # loading code; the TF path is
                                                    # simpler and still light-ish
                                                    # for our event-rate workload.

Model download: the first run pulls ~17MB from TF Hub. Cache it offline by
exporting TFHUB_CACHE_DIR.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

import numpy as np

from ....pipeline.types import AudioFrame, Detection, DetectionSet, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)


YAMNET_HANDLE = "https://tfhub.dev/google/yamnet/1"
YAMNET_WINDOW_SEC = 0.96
YAMNET_SAMPLE_RATE = 16000


class AudioClassifierNode(Node):
    TYPE_ID = "detector.audio_class"
    UI_CATEGORY = "detector"
    INPUTS = (Port("audio", PortType.AUDIO_FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "min_score": {
                "type": "number", "default": 0.3, "minimum": 0.0, "maximum": 1.0,
                "description": "Emit only classes scoring at least this",
            },
            "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 521,
                       "description": "Cap on classes per inference"},
            "classes": {
                "type": "array", "items": {"type": "string"},
                "default": [],
                "description": "If non-empty, only emit Detections whose YAMNet "
                               "class name matches one of these (case-insensitive substring). "
                               "E.g. ['Glass', 'Dog', 'Smoke', 'Siren', 'Speech']",
            },
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._model: Any = None
        self._labels: list[str] = []
        # Rolling buffer of incoming PCM samples. Sized to one YAMNet window.
        self._buf: deque[np.ndarray] = deque()
        self._buf_len: int = 0
        self._target_len: int = int(YAMNET_WINDOW_SEC * YAMNET_SAMPLE_RATE)
        self._window_start_ns: int = 0

    async def setup(self) -> None:
        try:
            import tensorflow_hub as hub  # type: ignore
            import tensorflow as tf  # type: ignore  # noqa: F401 — imported for TF Hub side effects
        except ImportError as exc:
            raise RuntimeError(
                "detector.audio_class needs tensorflow + tensorflow_hub.\n"
                "Install with: pip install tensorflow-cpu tensorflow_hub"
            ) from exc

        self._model = await asyncio.to_thread(hub.load, YAMNET_HANDLE)
        # YAMNet's class_map.csv lives on the model object as an asset path.
        import csv

        def _load_labels(path: str) -> list[str]:
            with open(path) as f:
                reader = csv.reader(f)
                next(reader)  # header
                return [row[2] for row in reader]
        path = self._model.class_map_path().numpy().decode("utf-8")
        self._labels = await asyncio.to_thread(_load_labels, path)
        log.info("audio_class loaded YAMNet (%d classes)", len(self._labels))

    async def process(self, **inputs: Any) -> dict[str, Any]:
        af: AudioFrame | None = inputs.get("audio")
        if af is None or self._model is None:
            return {}

        # Accept whatever sample rate, resample to 16k if needed.
        samples = af.data
        if af.sample_rate != YAMNET_SAMPLE_RATE:
            samples = _resample_linear(samples, af.sample_rate, YAMNET_SAMPLE_RATE)

        if not self._buf:
            self._window_start_ns = af.timestamp_ns
        self._buf.append(samples)
        self._buf_len += len(samples)
        if self._buf_len < self._target_len:
            return {}

        # We have a full window — concatenate, trim to exactly target_len, infer.
        window = np.concatenate(list(self._buf))[: self._target_len]
        # Reset the buffer fully — YAMNet windows don't overlap by default.
        self._buf.clear()
        self._buf_len = 0
        window_start_ns = self._window_start_ns
        self._window_start_ns = 0

        min_score = float(self.config.get("min_score", 0.3))
        top_k = int(self.config.get("top_k", 5))
        filter_classes = [c.lower() for c in (self.config.get("classes") or [])]

        def _run() -> list[Detection]:
            scores, _embeddings, _spectrogram = self._model(window)
            mean_scores = np.mean(scores.numpy(), axis=0)
            order = np.argsort(mean_scores)[::-1]
            out: list[Detection] = []
            for idx in order[:top_k]:
                score = float(mean_scores[idx])
                if score < min_score:
                    break
                label = self._labels[int(idx)] if int(idx) < len(self._labels) else str(idx)
                if filter_classes and not any(f in label.lower() for f in filter_classes):
                    continue
                out.append(Detection(
                    label=label, score=score, class_id=int(idx),
                    bbox=(0.0, 0.0, 0.0, 0.0),
                    attrs={
                        "window_start_ns": int(window_start_ns),
                        "duration_s": YAMNET_WINDOW_SEC,
                        "modality": "audio",
                    },
                ))
            return out

        dets = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=af.camera_id, timestamp_ns=af.timestamp_ns,
            detections=dets, source_node=self.node_id,
        )}


def _resample_linear(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Simple linear-interpolation resample. Adequate for ~10–48kHz pairs
    feeding a YAMNet-scale classifier; for higher-fidelity downstream use
    scipy.signal.resample_poly if you need it.
    """
    if src_rate == dst_rate:
        return samples
    src_idx = np.arange(len(samples), dtype=np.float32)
    target_len = int(round(len(samples) * dst_rate / src_rate))
    dst_idx = np.linspace(0, len(samples) - 1, target_len, dtype=np.float32)
    return np.interp(dst_idx, src_idx, samples).astype(np.float32)
