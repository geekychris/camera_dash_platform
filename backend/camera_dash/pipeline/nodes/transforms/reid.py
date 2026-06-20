"""Re-identification across cameras via CLIP image embeddings.

For each Detection bbox: crop the image patch → embed via a small CLIP model
→ compare to a shared rolling history of recent embeddings. If the new
embedding's cosine similarity to a historical one exceeds the threshold,
inherit that entity's global ``track_id``. Otherwise mint a fresh global id.

Unlike ``transform.tracker`` (ByteTrack) which only links detections within
a single camera over time, ``transform.reid`` links them ACROSS cameras and
across short gaps. Drop it at the tail of any detector and a person that
walks from camera A to camera B keeps the same ``track_id`` in attrs.

History is kept in a class-level dict keyed by the visual category (label).
Every camera_dash pipeline that includes a ``transform.reid`` node shares
the same history, so multiple pipelines can collaborate on the same track
namespace. Restart the pipeline to reset.

Embedding backend: prefers OpenAI's open_clip CPU/CUDA model when available
(via ``open_clip_torch``); falls back to a deterministic colour-histogram
hash for environments without torch — useful for the Pi 5 / Coral target
where pulling in torch+CLIP would be ~700MB.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

import numpy as np

from ....pipeline.types import DetectionSet, Frame, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)


# Shared cross-pipeline history. Key: label. Value: deque of
# (embedding, global_track_id, last_seen_monotonic).
_HISTORY: dict[str, deque[tuple[np.ndarray, int, float]]] = {}
_NEXT_TRACK_ID = 1


class ReidNode(Node):
    TYPE_ID = "transform.reid"
    UI_CATEGORY = "transform"
    INPUTS = (
        Port("detections", PortType.DETECTIONS),
        Port("frame", PortType.FRAME),
    )
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "similarity_threshold": {
                "type": "number", "default": 0.78, "minimum": 0.0, "maximum": 1.0,
                "description": "Cosine similarity above which a new detection inherits an existing track_id",
            },
            "history_seconds": {
                "type": "number", "default": 60.0, "minimum": 1.0,
                "description": "Drop historical embeddings older than this many seconds",
            },
            "history_size": {
                "type": "integer", "default": 200, "minimum": 1, "maximum": 5000,
                "description": "Max embeddings retained per label across all cameras",
            },
            "backend": {
                "type": "string", "enum": ["auto", "clip", "histogram"],
                "default": "auto",
                "description": "auto = clip if open_clip importable, else histogram",
            },
            "min_score": {
                "type": "number", "default": 0.30, "minimum": 0.0, "maximum": 1.0,
                "description": "Skip Re-ID on detections under this confidence — embedding low-confidence "
                               "crops causes track drift",
            },
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._embed: Any = None
        self._backend: str = "histogram"

    async def setup(self) -> None:
        requested = str(self.config.get("backend", "auto"))
        if requested in ("auto", "clip"):
            try:
                import open_clip  # type: ignore
                import torch  # type: ignore
                model, _, preprocess = open_clip.create_model_and_transforms(
                    "ViT-B-32", pretrained="laion2b_s34b_b79k"
                )
                model.eval()
                device = "cuda" if torch.cuda.is_available() else "cpu"
                model = model.to(device)
                self._embed = _ClipEmbedder(model, preprocess, device)
                self._backend = "clip"
                log.info("transform.reid using CLIP embeddings on %s", device)
                return
            except Exception:
                if requested == "clip":
                    raise
                log.info("transform.reid: open_clip not available, falling back to histogram")
        self._embed = _HistogramEmbedder()
        self._backend = "histogram"

    async def process(self, **inputs: Any) -> dict[str, Any]:
        global _NEXT_TRACK_ID
        dets: DetectionSet | None = inputs.get("detections")
        frame: Frame | None = inputs.get("frame")
        if dets is None or frame is None or self._embed is None:
            return {"detections": dets} if dets is not None else {}
        if not dets.detections:
            return {"detections": dets}

        thr = float(self.config.get("similarity_threshold", 0.78))
        max_age = float(self.config.get("history_seconds", 60.0))
        history_size = int(self.config.get("history_size", 200))
        min_score = float(self.config.get("min_score", 0.30))
        now = time.monotonic()

        H, W = frame.data.shape[:2]
        for d in dets.detections:
            if d.score < min_score:
                continue
            x, y, w, h = d.bbox
            x1 = max(0, int(x))
            y1 = max(0, int(y))
            x2 = min(W, int(x + w))
            y2 = min(H, int(y + h))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = frame.data[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            try:
                emb = self._embed.embed(crop)
            except Exception:
                log.exception("transform.reid: embed failed")
                continue

            hist = _HISTORY.setdefault(d.label, deque(maxlen=history_size))
            # Age out stale entries from the FRONT (deque oldest-first).
            while hist and (now - hist[0][2]) > max_age:
                hist.popleft()

            best_id = -1
            best_sim = -1.0
            for vec, tid, _ in hist:
                sim = float(np.dot(emb, vec))  # both unit-norm
                if sim > best_sim:
                    best_sim = sim
                    best_id = tid
            if best_sim >= thr and best_id > 0:
                d.attrs["track_id"] = best_id
                d.attrs["reid_similarity"] = round(best_sim, 3)
            else:
                tid = _NEXT_TRACK_ID
                _NEXT_TRACK_ID += 1
                d.attrs["track_id"] = tid
                d.attrs["reid_similarity"] = round(best_sim, 3) if best_sim > 0 else 0.0
            d.attrs["reid_backend"] = self._backend
            hist.append((emb, int(d.attrs["track_id"]), now))

        return {"detections": dets}


class _ClipEmbedder:
    """Wrap an open_clip model so .embed(bgr_uint8) → unit-norm float32 vector."""

    def __init__(self, model: Any, preprocess: Any, device: str) -> None:
        self.model = model
        self.preprocess = preprocess
        self.device = device

    def embed(self, bgr: np.ndarray) -> np.ndarray:
        import torch  # type: ignore
        from PIL import Image  # type: ignore

        rgb = bgr[:, :, ::-1]
        img = Image.fromarray(rgb)
        tensor = self.preprocess(img).unsqueeze(0).to(self.device)
        with torch.no_grad():
            feats = self.model.encode_image(tensor)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats[0].cpu().numpy().astype(np.float32)


class _HistogramEmbedder:
    """Fallback when CLIP isn't available: 3D BGR histogram, L2-normalised.

    Much weaker than CLIP — looks for visual similarity in colour space only,
    so it won't tell a red shirt from a red car. But it requires nothing
    beyond opencv-python (already a runtime dep) so the Re-ID node still
    functions on minimal Pi installs. Good enough for "match the same red
    jacket across cameras within a minute."
    """

    BINS = (8, 8, 8)

    def embed(self, bgr: np.ndarray) -> np.ndarray:
        import cv2

        hist = cv2.calcHist([bgr], [0, 1, 2], None, self.BINS, [0, 256] * 3)
        vec = hist.flatten().astype(np.float32)
        n = float(np.linalg.norm(vec))
        return vec / n if n > 0 else vec
