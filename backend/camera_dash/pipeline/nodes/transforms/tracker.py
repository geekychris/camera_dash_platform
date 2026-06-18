"""Object tracker — turns per-frame detections into temporally consistent tracks.

Uses ByteTrack via the ``supervision`` package. Takes :class:`DetectionSet` in,
emits :class:`DetectionSet` with each :class:`Detection`'s ``track_id``
populated. Lost tracks get pruned after ``max_lost_frames`` frames missing.

Once a tracker is in your pipeline, downstream nodes can do meaningful things
that single-frame detections can't:

* fire "X entered" / "X left" exactly once
* compute dwell time (how long has track_id 7 been visible?)
* count unique objects across a session
"""

from __future__ import annotations

import asyncio
from typing import Any

from ....pipeline.types import Detection, DetectionSet, PortType
from ...node import Node, Port


class TrackerNode(Node):
    TYPE_ID = "transform.tracker"
    UI_CATEGORY = "transform"
    INPUTS = (Port("payload", PortType.DETECTIONS),)
    OUTPUTS = (Port("payload", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "frame_rate": {"type": "integer", "default": 15,
                           "description": "Tracker tuning parameter; set close to pipeline fps"},
            "track_activation_threshold": {"type": "number", "default": 0.25,
                                            "description": "Min detection score to start a track"},
            "lost_track_buffer": {"type": "integer", "default": 30,
                                   "description": "Frames a track can be missing before pruning"},
            "minimum_matching_threshold": {"type": "number", "default": 0.8,
                                            "description": "IoU threshold for matching detections to tracks"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._tracker: Any = None

    async def setup(self) -> None:
        try:
            from supervision import ByteTrack  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "tracker requires supervision: pip install supervision"
            ) from exc
        self._tracker = ByteTrack(
            track_activation_threshold=float(self.config.get("track_activation_threshold", 0.25)),
            lost_track_buffer=int(self.config.get("lost_track_buffer", 30)),
            minimum_matching_threshold=float(self.config.get("minimum_matching_threshold", 0.8)),
            frame_rate=int(self.config.get("frame_rate", 15)),
        )

    async def process(self, **inputs: Any) -> dict[str, Any]:
        dets: DetectionSet | None = inputs.get("payload")
        if dets is None:
            return {}

        def _track() -> DetectionSet:
            import numpy as np
            from supervision import Detections  # type: ignore

            if not dets.detections:
                # Tick the tracker with empty input so lost-track timers still advance.
                empty = Detections.empty()
                self._tracker.update_with_detections(empty)
                return dets

            xyxy = np.array([[d.bbox[0], d.bbox[1], d.bbox[0] + d.bbox[2], d.bbox[1] + d.bbox[3]]
                              for d in dets.detections], dtype=np.float32)
            conf = np.array([d.score for d in dets.detections], dtype=np.float32)
            cls = np.array([d.class_id if d.class_id is not None else 0
                             for d in dets.detections], dtype=np.int64)

            sv_dets = Detections(xyxy=xyxy, confidence=conf, class_id=cls)
            tracked = self._tracker.update_with_detections(sv_dets)

            # supervision returns only detections that got assigned a track; map back.
            new_dets: list[Detection] = []
            for i in range(len(tracked.xyxy)):
                x1, y1, x2, y2 = tracked.xyxy[i]
                tid = int(tracked.tracker_id[i]) if tracked.tracker_id is not None else None
                cid = int(tracked.class_id[i]) if tracked.class_id is not None else None
                score = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
                # Recover the label from the original set by class id (best effort)
                label = next((d.label for d in dets.detections if d.class_id == cid), str(cid or ""))
                new_dets.append(Detection(
                    label=label, score=score, class_id=cid, track_id=tid,
                    bbox=(float(x1), float(y1), float(x2 - x1), float(y2 - y1)),
                ))
            return DetectionSet(
                camera_id=dets.camera_id, timestamp_ns=dets.timestamp_ns,
                detections=new_dets, source_node=self.node_id,
            )

        out = await asyncio.to_thread(_track)
        return {"payload": out}
