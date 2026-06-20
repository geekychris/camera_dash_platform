# camera_dash — Node Reference

All 56 built-in nodes, organized by category. Each entry shows its `type_id`, input/output ports, and key config options.

For the live, machine-readable catalog (with full JSON Schema for each config), hit `GET /api/plugins` — it's what the editor's palette is built from.

**Port types**: `FRAME` (video, drop-oldest), `DEPTH_FRAME` (uint16 mm matrix), `AUDIO_FRAME` (PCM), `DETECTIONS` (bbox sets, drop-oldest), `EVENT` (notifications, keep-all), `TRIGGER` (recording triggers, keep-all).

---

## Sources (4)

### `source.camera`
Subscribes a pipeline to a configured camera.

| | |
|---|---|
| Inputs | — |
| Outputs | `frame: FRAME` |
| Config | `camera_id` (required), `queue_depth` (default 2) |

### `source.camera_depth`
Subscribes to the depth channel of a depth-capable camera (Kinect v1/v2, OAK-D, RealSense).

| | |
|---|---|
| Inputs | — |
| Outputs | `depth: DEPTH_FRAME` (uint16 mm matrix) |
| Config | `camera_id` (required), `queue_depth` (default 2) |

### `source.audio`
Captures PCM audio from the host's PortAudio device (system mic, USB mic, etc.).

| | |
|---|---|
| Inputs | — |
| Outputs | `audio: AUDIO_FRAME` |
| Config | `camera_id` (bus key, default `"mic_default"`), `device` (default `"default"`), `sample_rate` (default 16000), `chunk_ms` (default 100), `channels` (default 1) |

### `source.file`
Plays a video file as if it were a camera. Useful for testing pipelines without hardware.

| | |
|---|---|
| Inputs | — |
| Outputs | `frame: FRAME` |
| Config | `path` (required), `camera_id` (default `"file"`), `loop` (default true), `fps` (default 30) |

---

## Detectors (15)

### `detector.yolo`
Ultralytics YOLO (v8/v11). Fixed COCO labels (person, car, dog, cat, bicycle, … 80 classes).

| | |
|---|---|
| Inputs | `frame: FRAME` |
| Outputs | `detections: DETECTIONS` |
| Config | `model` (default `yolov8n.pt`), `device` (cpu/mps/cuda), `conf` (0.25), `iou` (0.45), `classes` (whitelist), `imgsz` (640) |

### `detector.yolo_world`
Open-vocabulary YOLO — text-promptable. Use for classes not in COCO (scorpion, drone, safety helmet, etc.).

| | |
|---|---|
| Inputs | `frame: FRAME` |
| Outputs | `detections: DETECTIONS` |
| Config | `model` (default `yolov8s-worldv2.pt`), `classes` (free-text array, required), `device`, `conf` (default 0.1 — lower than YOLO because open-vocab needs it) |

### `detector.onnx`
Generic ONNX Runtime detector. Currently assumes YOLOv8 output shape.

| | |
|---|---|
| Config | `model_path` (required), `providers`, `input_size`, `labels`, `conf` |

### `detector.opencv_dnn`
OpenCV DNN (Caffe / TensorFlow / Darknet / ONNX). Supports SSD-style outputs.

| | |
|---|---|
| Config | `model_path`, `config_path`, `labels`, `input_size`, `scale`, `mean`, `conf` |

### `detector.mediapipe`
MediaPipe face detection.

| | |
|---|---|
| Config | `model_selection` (0 short-range, 1 full-range), `min_confidence` |

### `detector.mog2`
OpenCV MOG2 background subtraction — fires on moving blobs. No labels needed; runs on FLIR too.

| | |
|---|---|
| Config | `history`, `var_threshold`, `detect_shadows`, `min_area` |

### `detector.optical_flow`
Dense Farneback optical flow. Emits a single detection when mean magnitude exceeds threshold.

| | |
|---|---|
| Config | `pyr_scale`, `levels`, `winsize`, `iterations`, `magnitude_threshold` |

### `detector.vision_llm`
Calls Claude on a frame, emits an Event with the model's text description. Use for rich alert messages.

| | |
|---|---|
| Inputs | `frame: FRAME`, `trigger: EVENT` (optional, recommended) |
| Outputs | `event: EVENT` |
| Config | `model` (default `claude-haiku-4-5`), `prompt`, `min_interval_s` (default 30 — throttles to save tokens), `max_tokens`, `api_key_env`, `trigger_only` (default true), `jpeg_quality` |

### `detector.pose`
MediaPipe pose with 33 body landmarks. Includes a simple fall-detection heuristic (shoulder→ankle vector becomes more horizontal than vertical).

| | |
|---|---|
| Config | `model_complexity` (0/1/2), `min_confidence`, `detect_fall` |
| Output detail | Each detection has label `"pose"` or `"pose:fallen"` and the raw landmarks in `attrs["landmarks"]` |

### `detector.segmentation`
YOLOv8 instance segmentation. Each detection carries a pixel mask in `attrs["mask"]`.

| | |
|---|---|
| Config | `model` (default `yolov8n-seg.pt`), `device`, `conf`, `classes`, `include_masks` |

### `detector.ocr`
EasyOCR. If upstream `detections` is connected, OCRs inside each bbox (ALPR-style); otherwise OCRs the whole frame.

| | |
|---|---|
| Inputs | `frame: FRAME`, `detections: DETECTIONS` (optional) |
| Config | `languages` (default `["en"]`), `gpu`, `crop_to_bboxes`, `min_confidence`, `label_prefix` |

### `detector.anomaly`
Long-history MOG2 + min-area filter — flags significant scene changes. Each detection has a "novelty" score in `attrs["novelty"]`.

| | |
|---|---|
| Config | `history` (1000), `var_threshold` (30), `min_area` (1500), `warmup_frames` (50) |

### `detector.depth_background`
Builds a depth median background. Anything closer than background by `delta_mm` becomes a detection.

| | |
|---|---|
| Inputs | `depth: DEPTH_FRAME` |
| Outputs | `detections: DETECTIONS` |
| Config | `delta_mm` (300), `min_area` (1500), `history` (200), `min_depth_mm` (300), `max_depth_mm` (6000) |

### `detector.coral_yolo`
Google Coral Edge TPU YOLO inference via PyCoral. Drop in an Edge-TPU-compiled `.tflite` model; inference cost is ~1-2W on the TPU vs ~6W for CPU YOLO. COCO labels baked in if `labels_path` is empty. Requires PyCoral installed separately (no pip wheel for aarch64 Pi 5 — install via apt or build from source).

| | |
|---|---|
| Inputs | `frame: FRAME` |
| Outputs | `detections: DETECTIONS` |
| Config | `model_path` (required, `*_edgetpu.tflite`), `labels_path` (optional), `conf` (0.25), `iou` (0.45), `classes` (whitelist), `max_detections` (100) |

### `detector.audio_class`
YAMNet (TF Hub) classifies 521 AudioSet sound classes on rolling 0.96s windows. Emits Detections with `bbox=(0,0,0,0)` and `attrs["modality"]="audio"`. Pair with `condition.cooldown` (`scope: per_camera_kind`) to suppress duplicates.

| | |
|---|---|
| Inputs | `audio: AUDIO_FRAME` |
| Outputs | `detections: DETECTIONS` |
| Config | `min_score` (0.3), `top_k` (5), `classes` (case-insensitive substring whitelist; e.g. `["Glass", "Dog", "Smoke", "Siren", "Speech"]`) |

---

## Transforms (11)

### `transform.resize`
Resize a frame. Discards `radiometric` (don't use on thermal frames if you want temp-on-hover to work).

| | |
|---|---|
| Config | `width`, `height` (both required), `interpolation` (linear/nearest/area/cubic) |

### `transform.crop`
Crop a fixed ROI. Preserves `radiometric`.

| | |
|---|---|
| Config | `x`, `y`, `width`, `height` |

### `transform.colormap`
Apply an OpenCV colormap. Useful for visualizing thermal differently from the default.

| | |
|---|---|
| Config | `colormap` (inferno/jet/hot/viridis/magma/plasma/turbo), `source` (`data` or `radiometric`) |

### `transform.annotate`
Draw bounding boxes + labels onto a frame. Pair with `sink.stream` to surface the annotated stream on the dashboard.

| | |
|---|---|
| Inputs | `frame: FRAME`, `detections: DETECTIONS` |
| Config | `color` (BGR array), `thickness`, `show_score` |

### `transform.throttle`
Pass-through DETECTIONS at most every `interval_s` seconds. Engine's drop-oldest queue takes care of dropping the in-between frames.

| | |
|---|---|
| Config | `interval_s` (default 5.0) |

### `transform.tracker`
ByteTrack via `supervision`. Adds persistent `track_id` to each detection across frames. **Required** if you want `condition.zone` or `condition.line_crossing` to be meaningful.

| | |
|---|---|
| Config | `frame_rate` (~ pipeline fps), `track_activation_threshold`, `lost_track_buffer`, `minimum_matching_threshold` |

### `transform.privacy_mask`
Blur/pixelate/blackout a polygon region or matching detections (e.g. all faces).

| | |
|---|---|
| Inputs | `frame: FRAME`, `detections: DETECTIONS` (optional) |
| Config | `mode` (polygon/detections/both), `polygon`, `classes`, `blur_kernel`, `method` (blur/pixelate/solid) |

### `transform.frame_sample`
Throttles a `frame` stream down to N fps without altering the frame.

| | |
|---|---|
| Inputs | `frame: FRAME` |
| Outputs | `frame: FRAME` |
| Config | `fps` (default 1.0) |

### `transform.depth_colormap`
Colormaps a depth matrix to a regular FRAME for dashboard display. Pair with `broadcast.stream`.

| | |
|---|---|
| Inputs | `depth: DEPTH_FRAME` |
| Outputs | `frame: FRAME` |
| Config | `colormap` (turbo/jet/viridis), `near_mm` (300), `far_mm` (4000), `invalid_color` ([0,0,0]) |

### `transform.enrich_with_depth`
Adds `depth_m` and `box_depth_m` to each detection's `attrs` by sampling a paired depth frame at the box centre.

| | |
|---|---|
| Inputs | `detections: DETECTIONS`, `depth: DEPTH_FRAME` |
| Outputs | `detections: DETECTIONS` |
| Config | `sample_window` (5 — pixel window for median) |

### `transform.reid`
Cross-pipeline re-identification. Embeds each detection's crop with CLIP (or histogram fallback) and stamps a global `track_id` in `attrs` for any detection that cosine-matches a recent embedding from any other pipeline. Embedding history is shared in-process across all `transform.reid` nodes, so the same person tracked on camera A keeps their id when picked up on camera B.

| | |
|---|---|
| Inputs | `frame: FRAME`, `detections: DETECTIONS` |
| Outputs | `detections: DETECTIONS` |
| Config | `similarity_threshold` (0.78), `history_seconds` (60), `history_size` (200), `backend` (auto/clip/histogram), `min_score` (0.30 — skip low-confidence crops to avoid track drift) |

---

## Conditions (10)

Condition nodes have two outputs: `match` and `no_match`. The graph routes events based on which fired. Match events are also broadcast to the EventBus so the dashboard's log/alert/timeline tiles see them.

### `condition.metadata_match`
Boolean expression over each detection. Safe AST (no `__import__`, no attribute escape, builtin whitelist).

| | |
|---|---|
| Config | `expression` (e.g. `d.label == 'person' and d.score > 0.7`), `any` (default true — match if any detection matches) |

### `condition.temperature_gate`
Thermal-specific. Fires when any radiometric pixel exceeds the threshold (over the whole frame or inside upstream bboxes).

| | |
|---|---|
| Config | `min_celsius`, `max_celsius`, `region` (`whole` or `bbox`) |

### `condition.zone`
Polygon zone. Use after `transform.tracker` so each event fires exactly once per crossing/dwell event.

| | |
|---|---|
| Config | `polygon` (pixel coords), `fire_on` (enter/leave/dwell), `dwell_s`, `classes` (whitelist) |
| Use the dashboard's `▱` button to draw the polygon visually |

### `condition.counter`
Threshold on detection count.

| | |
|---|---|
| Config | `label` (filter, empty = all), `min_count` |

### `condition.line_crossing`
Fires when a tracked object crosses a configured line. Requires upstream tracker.

| | |
|---|---|
| Config | `line` ([[x1,y1], [x2,y2]]), `direction` (any/left_to_right/right_to_left), `classes` |

### `condition.schedule`
Time-of-day gate. Only passes events through during configured windows. Supports wrap-around (`start: "21:00", end: "06:00"`) and weekday filters.

| | |
|---|---|
| Config | `windows` ([{start, end, days}]) |

### `condition.cooldown`
Debounce — drops events arriving within `cooldown_s` of the last passed one. `scope` controls the cooldown key (global / per_kind / per_camera / per_camera_kind).

| | |
|---|---|
| Config | `cooldown_s` (default 60), `scope` (default `per_camera_kind`) |

### `condition.distance_gate`
Fires when a detection enriched with depth is closer than (or farther than) a threshold. Pair after `transform.enrich_with_depth`.

| | |
|---|---|
| Inputs | `detections: DETECTIONS` |
| Config | `max_distance_m` (3.0), `min_distance_m` (0.0), `attr` (`depth_m`) |

### `condition.depth_volume`
Fires when a contiguous volume in a `DEPTH_FRAME` enters or exits a configured 3D box.

| | |
|---|---|
| Inputs | `depth: DEPTH_FRAME` |
| Config | `box_mm` (per-axis min/max bounds), `min_voxels` (200), `mode` (enter/exit/both) |

### `condition.fall_detection`
Heuristic fall detector from pose keypoints — flags rapid vertical hip-to-shoulder collapse.

| | |
|---|---|
| Inputs | `detections: DETECTIONS` (from `detector.pose`) |
| Config | `min_speed` (0.6 m/s), `min_drop_ratio` (0.4), `lock_seconds` (3.0) |

---

## Sinks (14)

Sinks are terminal. They accept `payload: EVENT` (which the validator also accepts DETECTIONS for, since they're often what you want to forward).

### `sink.console`
Logs each payload via Python logging (visible on backend stderr). Also rebroadcasts to the event bus by default so dashboard log tiles see it.

| | |
|---|---|
| Config | `level`, `format` (pretty/json/compact), `prefix`, `broadcast` |

### `sink.mqtt`
Publishes JSON to an MQTT topic.

| | |
|---|---|
| Config | `broker` (`tcp://host:port`), `topic`, `qos`, `retain`, `client_id` |

### `sink.kafka`
Aiokafka producer. Sends JSON-encoded payloads to a Kafka topic.

| | |
|---|---|
| Config | `bootstrap_servers`, `topic`, `client_id` |

### `sink.webhook`
HTTP POST (or PUT) JSON to a URL.

| | |
|---|---|
| Config | `url`, `method`, `headers`, `timeout_s` |

### `sink.recorder`
Records an mp4 clip when triggered. Uses the camera's ring buffer for pre-roll and pulls live for post-roll.

| | |
|---|---|
| Inputs | `trigger: EVENT` |
| Config | `camera_id` (override; defaults to event.camera_id), `pre_roll_s`, `post_roll_s`, `container`, `cooldown_s` |
| Output | Writes mp4 + thumbnail JPG to `data/clips/`; persists a Clip row |

### `sink.sqlite`
Persists each event to the `events` table for the historical `/api/events` query.

| | |
|---|---|
| Config | `kind_override` |

### `sink.stream`
Re-publishes the input frame as a derived video stream — appears as a tile on the dashboard alongside raw cameras. Usual placement: after `transform.annotate`.

| | |
|---|---|
| Inputs | `frame: FRAME` |
| Config | `label`, `fps` |

### `sink.telegram`
Telegram bot push. Setup via @BotFather; supply `bot_token` + `chat_id` (or via env vars `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`).

| | |
|---|---|
| Config | `template` (`{kind}`, `{camera_id}`, `{summary}`, `{pipeline_id}`) |

### `sink.ntfy`
ntfy.sh push. Free, no account. Pick a unique-ish topic name and subscribe from the [ntfy mobile app](https://ntfy.sh).

| | |
|---|---|
| Config | `topic` (required), `base_url` (default `https://ntfy.sh`), `priority` (1-5), `tags`, `template` |

### `sink.pushover`
Pushover push (one-time $5). Supports emergency-priority alerts that require acknowledgement.

| | |
|---|---|
| Config | `app_token`, `user_key`, `priority` (-2..2), `title`, `template` |

### `sink.email`
SMTP email. Use for daily digests or low-noise alerts. Auth via env vars (`SMTP_USER` / `SMTP_PASSWORD`).

| | |
|---|---|
| Config | `host`, `port`, `use_tls`, `from_addr`, `to_addrs`, `subject_template`, `body_template` |

### `sink.slack`
Slack incoming-webhook. Same template syntax as the other notification sinks.

| | |
|---|---|
| Config | `webhook_url` (or `webhook_url_env`), `template`, `username`, `icon_emoji` |

### `sink.jsonl`
Append each event as JSON-lines to a rolling file on disk. Good for offline ingestion or audit.

| | |
|---|---|
| Config | `path` (required), `rotate_mb` (default 50) |

### `sink.point_cloud`
Back-projects each `DEPTH_FRAME` through pinhole intrinsics and writes a `.ply` per frame (rate-limited). Pair with `transform.frame_sample` to control write rate.

| | |
|---|---|
| Inputs | `depth: DEPTH_FRAME` |
| Config | `out_dir` (required), `fx`/`fy`/`cx`/`cy` (Kinect v1 factory defaults), `max_mm` (6000), `min_mm` (300), `downsample` (2) |

### `sink.home_assistant`
Calls the Home Assistant REST API. Two modes: (a) `service` + `service_data` for arbitrary service calls; (b) `entity_id` + `action` (`on`/`off`/`toggle`) shorthand. Per-target cooldown so a chatty trigger doesn't hammer HA.

| | |
|---|---|
| Config | `url_env` (`HOME_ASSISTANT_URL`), `token_env` (`HOME_ASSISTANT_TOKEN`), `service`, `service_data`, `entity_id`, `action`, `cooldown_s` (5.0) |

---

## Authoring tip

Bigger conditional flow lives in the graph itself, not in node config. Need to react when one of three pipelines fires? Don't write a giant boolean — wire all three to a single sink, or to a `condition.cooldown` node that dedupes. The engine's DAG is the conditional fabric.
