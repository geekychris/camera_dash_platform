"""Coral Edge TPU YOLO detector — runs YOLO inference on a Google Coral
USB Accelerator or PCIe/M.2 module.

Sibling to ``detector.yolo`` (Ultralytics, CPU/MPS/CUDA). Use this node when
you have a Coral plugged in — inference moves off the CPU and onto the Edge
TPU, freeing the Pi 5's cores for capture / encoding / other pipelines.

Model: int8-quantised + Edge-TPU-compiled YOLO. You can grab pre-compiled
models from the PyCoral examples or compile your own with `edgetpu_compiler`.
Common path: download ``yolov8n_int8_edgetpu.tflite`` from a Coral model zoo
(e.g. https://github.com/google-coral/test_data) and point at it via the
``model_path`` config.

Install on the host:
    sudo apt install libedgetpu1-std python3-pycoral   # Debian/Ubuntu
    pip install pycoral tflite-runtime                  # Fedora/Arch

The ``pycoral`` import is deferred to ``setup()`` so the rest of the platform
keeps loading without it — if you don't have a Coral or haven't installed
the runtime, this node simply won't start (it'll throw at pipeline start
time with a clear message, not at module import).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import numpy as np

from ....pipeline.types import Detection, DetectionSet, Frame, PortType
from ...node import Node, Port

log = logging.getLogger(__name__)

# COCO label names — the default training corpus for YOLOv8/v11. Used when
# the labels file isn't supplied. Index → name in standard YOLO order.
COCO_LABELS = (
    "person bicycle car motorcycle airplane bus train truck boat traffic light "
    "fire hydrant stop sign parking meter bench bird cat dog horse sheep cow "
    "elephant bear zebra giraffe backpack umbrella handbag tie suitcase frisbee "
    "skis snowboard sports ball kite baseball bat baseball glove skateboard "
    "surfboard tennis racket bottle wine glass cup fork knife spoon bowl banana "
    "apple sandwich orange broccoli carrot hot dog pizza donut cake chair couch "
    "potted plant bed dining table toilet tv laptop mouse remote keyboard cell phone "
    "microwave oven toaster sink refrigerator book clock vase scissors teddy bear "
    "hair drier toothbrush"
).split()


class CoralYoloNode(Node):
    TYPE_ID = "detector.coral_yolo"
    UI_CATEGORY = "detector"
    INPUTS = (Port("frame", PortType.FRAME),)
    OUTPUTS = (Port("detections", PortType.DETECTIONS),)
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["model_path"],
        "properties": {
            "model_path": {
                "type": "string",
                "description": "Path to an Edge-TPU-compiled .tflite YOLO model "
                               "(usually named *_edgetpu.tflite)",
            },
            "labels_path": {
                "type": "string", "default": "",
                "description": "Optional path to a newline-separated labels file. "
                               "Empty = COCO classes baked in.",
            },
            "conf": {"type": "number", "default": 0.25, "minimum": 0.0, "maximum": 1.0},
            "iou": {"type": "number", "default": 0.45, "minimum": 0.0, "maximum": 1.0,
                     "description": "NMS IoU threshold"},
            "classes": {"type": "array", "items": {"type": "string"}, "default": [],
                         "description": "If non-empty, only emit detections with these labels"},
            "max_detections": {"type": "integer", "default": 100, "minimum": 1},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._interp: Any = None
        self._input_size: tuple[int, int] = (640, 640)
        self._input_idx: int = 0
        self._output_idx: int = 0
        self._labels: tuple[str, ...] = COCO_LABELS

    async def setup(self) -> None:
        try:
            from pycoral.utils.edgetpu import make_interpreter  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "detector.coral_yolo needs pycoral. Install on Debian/Ubuntu:\n"
                "  sudo apt install libedgetpu1-std python3-pycoral\n"
                "Or via pip: pip install pycoral tflite-runtime"
            ) from exc

        model_path = str(self.config.get("model_path") or "")
        if not model_path or not Path(model_path).exists():
            raise RuntimeError(
                f"detector.coral_yolo: model_path={model_path!r} not found. "
                f"Download a YOLO _edgetpu.tflite from a Coral model zoo and "
                f"point the node at it.")

        # make_interpreter handles the libedgetpu delegate registration for us.
        self._interp = await asyncio.to_thread(make_interpreter, model_path)
        await asyncio.to_thread(self._interp.allocate_tensors)
        in_details = self._interp.get_input_details()[0]
        out_details = self._interp.get_output_details()[0]
        self._input_idx = in_details["index"]
        self._output_idx = out_details["index"]
        shape = in_details["shape"]  # [1, H, W, 3]
        self._input_size = (int(shape[2]), int(shape[1]))

        labels_path = str(self.config.get("labels_path") or "")
        if labels_path and Path(labels_path).exists():
            self._labels = tuple(Path(labels_path).read_text().strip().splitlines())
        log.info("coral_yolo loaded %s (input=%s, %d labels)",
                 model_path, self._input_size, len(self._labels))

    async def process(self, **inputs: Any) -> dict[str, Any]:
        import cv2

        frame: Frame | None = inputs.get("frame")
        if frame is None or self._interp is None:
            return {}
        conf_min = float(self.config.get("conf", 0.25))
        iou_thr = float(self.config.get("iou", 0.45))
        max_det = int(self.config.get("max_detections", 100))
        filter_classes = set(self.config.get("classes") or [])

        def _run() -> list[Detection]:
            w, h = self._input_size
            img = cv2.resize(frame.data, (w, h), interpolation=cv2.INTER_LINEAR)
            # YOLO Edge TPU models expect RGB int8; OpenCV gives BGR. Quantised
            # inputs use the raw uint8 — no scaling needed for int8 models.
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            inp = img[np.newaxis, ...].astype(np.uint8)
            self._interp.set_tensor(self._input_idx, inp)
            self._interp.invoke()
            out = self._interp.get_tensor(self._output_idx)
            # Layout varies by export. Typical YOLOv8 export: (1, 84, N) where
            # rows 0..3 are bbox xywh (normalised), rows 4..83 are class scores.
            arr = out[0]
            if arr.shape[0] < arr.shape[1]:  # (84, N)
                arr = arr.T  # → (N, 84)
            # If int8, dequantise via the output details. Most _edgetpu models
            # auto-dequant in get_tensor; if not, scale + zero_point would apply.
            boxes_xywh = arr[:, :4]
            scores_all = arr[:, 4:]
            # Greedy filter: top score per detection.
            cls_idx = np.argmax(scores_all, axis=1)
            scores = scores_all[np.arange(scores_all.shape[0]), cls_idx]
            keep = scores >= conf_min
            if not keep.any():
                return []
            boxes_xywh = boxes_xywh[keep]
            cls_idx = cls_idx[keep]
            scores = scores[keep]
            # Convert (cx, cy, w, h) normalised → (x1, y1, x2, y2) in input px,
            # then scale back to original frame dimensions.
            cx, cy, bw, bh = boxes_xywh.T
            x1 = (cx - bw / 2) * frame.width
            y1 = (cy - bh / 2) * frame.height
            x2 = (cx + bw / 2) * frame.width
            y2 = (cy + bh / 2) * frame.height
            xyxy = np.stack([x1, y1, x2, y2], axis=1)
            # OpenCV NMS expects xywh int.
            nms_boxes = np.stack([x1, y1, x2 - x1, y2 - y1], axis=1).tolist()
            nms_scores = scores.tolist()
            keep_idx = cv2.dnn.NMSBoxes(nms_boxes, nms_scores, conf_min, iou_thr)
            if isinstance(keep_idx, np.ndarray):
                keep_idx = keep_idx.flatten().tolist()
            elif not keep_idx:
                return []
            dets: list[Detection] = []
            for i in keep_idx[:max_det]:
                label = (self._labels[int(cls_idx[i])]
                         if int(cls_idx[i]) < len(self._labels)
                         else str(int(cls_idx[i])))
                if filter_classes and label not in filter_classes:
                    continue
                bx1, by1, bx2, by2 = xyxy[i]
                dets.append(Detection(
                    label=label,
                    score=float(scores[i]),
                    class_id=int(cls_idx[i]),
                    bbox=(float(bx1), float(by1), float(bx2 - bx1), float(by2 - by1)),
                    attrs={"backend": "coral_edgetpu"},
                ))
            return dets

        detections = await asyncio.to_thread(_run)
        return {"detections": DetectionSet(
            camera_id=frame.camera_id, timestamp_ns=frame.timestamp_ns,
            detections=detections, source_node=self.node_id,
        )}
