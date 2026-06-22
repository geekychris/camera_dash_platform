/**
 * Pipeline recipes — pre-wired sub-graphs the editor can drop in as a single
 * "Insert recipe" action. The user picks a recipe, fills the small form, and
 * we append a complete chain of nodes + edges to the canvas. Existing graph
 * is not touched; the user can wire from the recipe's tail to their own
 * downstream nodes after insertion.
 *
 * Recipes are intentionally data-driven so adding new ones is a single
 * append. Each recipe describes:
 *  - what to ask the user (`fields`)
 *  - how to produce the nodes/edges (`build`)
 *
 * Conventions inside `build`:
 *  - Use the provided `id(typeId)` helper for every node id so they're
 *    namespaced and won't collide with the user's existing graph.
 *  - Return edges as `"<nodeId>.<portName>"` source/target strings, matching
 *    the format used in `examples/pipelines/*.json` and the editor's edge
 *    serializer.
 */

export type RecipeField =
  | { name: string; label: string; type: "camera"; required?: boolean; description?: string }
  | { name: string; label: string; type: "string"; default?: string; description?: string }
  | { name: string; label: string; type: "number"; default?: number; min?: number; max?: number; description?: string }
  | { name: string; label: string; type: "select"; options: string[]; default?: string; description?: string }
  | { name: string; label: string; type: "strings"; default?: string[]; description?: string }
  | { name: string; label: string; type: "polygon"; description?: string };

export type RecipeNode = {
  id: string;
  type: string;
  config: Record<string, unknown>;
};

export type RecipeEdge = { from: string; to: string };

export type Recipe = {
  id: string;
  name: string;
  description: string;
  category: "Detect" | "Notify" | "Record" | "Stream" | "Privacy" | "Audio" | "Depth" | "Multi-camera";
  fields: RecipeField[];
  build: (
    params: Record<string, unknown>,
    ctx: { id: (typeId: string) => string },
  ) => { nodes: RecipeNode[]; edges: RecipeEdge[] };
};

export const RECIPES: Recipe[] = [
  {
    id: "detect_notify",
    name: "Detect → debounce → notify",
    description:
      "Run a detector on one camera, filter to a class list, debounce, push to a notification sink.",
    category: "Notify",
    fields: [
      { name: "camera", label: "Camera", type: "camera", required: true },
      { name: "classes", label: "Classes", type: "strings", default: ["person"],
         description: "COCO labels — comma-separated. person, car, dog, etc." },
      { name: "min_conf", label: "Min confidence", type: "number", default: 0.4, min: 0, max: 1 },
      { name: "cooldown_s", label: "Cooldown (s)", type: "number", default: 60, min: 1 },
      { name: "sink", label: "Notify via", type: "select",
         options: ["sink.ntfy", "sink.telegram", "sink.slack", "sink.home_assistant", "sink.email"],
         default: "sink.ntfy" },
    ],
    build: ({ camera, classes, min_conf, cooldown_s, sink }, { id }) => {
      const src = id("source.camera"), yolo = id("detector.yolo"),
            match = id("condition.metadata_match"), cool = id("condition.cooldown"),
            snk = id(sink as string);
      return {
        nodes: [
          { id: src, type: "source.camera", config: { camera_id: camera } },
          { id: yolo, type: "detector.yolo", config: { classes, conf: min_conf } },
          { id: match, type: "condition.metadata_match",
             config: { expression: `d.score > ${min_conf}` } },
          { id: cool, type: "condition.cooldown",
             config: { cooldown_s, scope: "per_camera_kind" } },
          { id: snk, type: sink as string, config: configForSink(sink as string) },
        ],
        edges: [
          { from: `${src}.frame`, to: `${yolo}.frame` },
          { from: `${yolo}.detections`, to: `${match}.detections` },
          { from: `${match}.match`, to: `${cool}.payload` },
          { from: `${cool}.match`, to: `${snk}.payload` },
        ],
      };
    },
  },
  {
    id: "detect_record",
    name: "Detect → record clip",
    description:
      "Trigger the ring-buffer recorder with pre-roll + post-roll when a class is seen.",
    category: "Record",
    fields: [
      { name: "camera", label: "Camera", type: "camera", required: true },
      { name: "classes", label: "Classes", type: "strings", default: ["person"] },
      { name: "min_conf", label: "Min confidence", type: "number", default: 0.4, min: 0, max: 1 },
      { name: "pre_roll_s", label: "Pre-roll (s)", type: "number", default: 5, min: 0 },
      { name: "post_roll_s", label: "Post-roll (s)", type: "number", default: 25, min: 0 },
      { name: "cooldown_s", label: "Cooldown (s)", type: "number", default: 60, min: 1 },
    ],
    build: ({ camera, classes, min_conf, pre_roll_s, post_roll_s, cooldown_s }, { id }) => {
      const src = id("source.camera"), yolo = id("detector.yolo"),
            match = id("condition.metadata_match"), cool = id("condition.cooldown"),
            rec = id("sink.recorder");
      return {
        nodes: [
          { id: src, type: "source.camera", config: { camera_id: camera } },
          { id: yolo, type: "detector.yolo", config: { classes, conf: min_conf } },
          { id: match, type: "condition.metadata_match",
             config: { expression: `d.score > ${min_conf}` } },
          { id: cool, type: "condition.cooldown",
             config: { cooldown_s, scope: "per_camera" } },
          { id: rec, type: "sink.recorder",
             config: { pre_roll_s, post_roll_s, cooldown_s } },
        ],
        edges: [
          { from: `${src}.frame`, to: `${yolo}.frame` },
          { from: `${yolo}.detections`, to: `${match}.detections` },
          { from: `${match}.match`, to: `${cool}.payload` },
          { from: `${cool}.match`, to: `${rec}.trigger` },
        ],
      };
    },
  },
  {
    id: "annotated_stream",
    name: "Annotated derived stream",
    description:
      "Detector + annotate + broadcast.stream — the boxed result shows up as a dashboard tile.",
    category: "Stream",
    fields: [
      { name: "camera", label: "Camera", type: "camera", required: true },
      { name: "classes", label: "Classes", type: "strings", default: ["person"] },
      { name: "label", label: "Stream label", type: "string", default: "Annotated" },
      { name: "fps", label: "Output fps", type: "number", default: 15, min: 1, max: 60 },
    ],
    build: ({ camera, classes, label, fps }, { id }) => {
      const src = id("source.camera"), yolo = id("detector.yolo"),
            ann = id("transform.annotate"), out = id("broadcast.stream");
      return {
        nodes: [
          { id: src, type: "source.camera", config: { camera_id: camera } },
          { id: yolo, type: "detector.yolo", config: { classes, conf: 0.4 } },
          { id: ann, type: "transform.annotate", config: { thickness: 2 } },
          { id: out, type: "broadcast.stream", config: { label, fps } },
        ],
        edges: [
          { from: `${src}.frame`, to: `${yolo}.frame` },
          { from: `${yolo}.detections`, to: `${ann}.detections` },
          { from: `${src}.frame`, to: `${ann}.frame` },
          { from: `${ann}.frame`, to: `${out}.frame` },
        ],
      };
    },
  },
  {
    id: "line_counter",
    name: "Line-crossing counter",
    description:
      "Detector + tracker + line crossing — log every crossing to SQLite.",
    category: "Detect",
    fields: [
      { name: "camera", label: "Camera", type: "camera", required: true },
      { name: "classes", label: "Classes", type: "strings", default: ["person"] },
      { name: "y_frac", label: "Line height (0–1)", type: "number", default: 0.6, min: 0, max: 1,
         description: "Horizontal line across the frame at this fraction of the height" },
      { name: "kind", label: "Event kind", type: "string", default: "line_cross" },
    ],
    build: ({ camera, classes, y_frac, kind }, { id }) => {
      const src = id("source.camera"), yolo = id("detector.yolo"),
            trk = id("transform.tracker"), line = id("condition.line_crossing"),
            sql = id("sink.sqlite");
      return {
        nodes: [
          { id: src, type: "source.camera", config: { camera_id: camera } },
          { id: yolo, type: "detector.yolo", config: { classes, conf: 0.4 } },
          { id: trk, type: "transform.tracker", config: { frame_rate: 15 } },
          { id: line, type: "condition.line_crossing",
             config: { line: [[0.0, y_frac], [1.0, y_frac]], direction: "both" } },
          { id: sql, type: "sink.sqlite", config: { kind } },
        ],
        edges: [
          { from: `${src}.frame`, to: `${yolo}.frame` },
          { from: `${yolo}.detections`, to: `${trk}.payload` },
          { from: `${trk}.payload`, to: `${line}.detections` },
          { from: `${line}.match`, to: `${sql}.payload` },
        ],
      };
    },
  },
  {
    id: "thermal_hotspot",
    name: "Thermal hotspot alert",
    description:
      "FLIR Lepton + temperature_gate + cooldown + notify when any pixel exceeds threshold °C.",
    category: "Detect",
    fields: [
      { name: "camera", label: "FLIR camera", type: "camera", required: true,
         description: "Pick a PureThermal Lepton camera (radiometric)" },
      { name: "threshold_c", label: "Threshold (°C)", type: "number", default: 60, min: -40, max: 500 },
      { name: "cooldown_s", label: "Cooldown (s)", type: "number", default: 120, min: 1 },
      { name: "sink", label: "Notify via", type: "select",
         options: ["sink.ntfy", "sink.telegram", "sink.slack", "sink.home_assistant"],
         default: "sink.ntfy" },
    ],
    build: ({ camera, threshold_c, cooldown_s, sink }, { id }) => {
      const src = id("source.camera"), gate = id("condition.temperature_gate"),
            cool = id("condition.cooldown"), snk = id(sink as string);
      return {
        nodes: [
          { id: src, type: "source.camera", config: { camera_id: camera } },
          { id: gate, type: "condition.temperature_gate",
             config: { threshold_c, mode: "max" } },
          { id: cool, type: "condition.cooldown",
             config: { cooldown_s, scope: "per_camera" } },
          { id: snk, type: sink as string, config: configForSink(sink as string) },
        ],
        edges: [
          { from: `${src}.frame`, to: `${gate}.frame` },
          { from: `${gate}.match`, to: `${cool}.payload` },
          { from: `${cool}.match`, to: `${snk}.payload` },
        ],
      };
    },
  },
  {
    id: "audio_alert",
    name: "Audio event alert",
    description:
      "USB mic + YAMNet + cooldown + notify when a target sound class fires.",
    category: "Audio",
    fields: [
      { name: "mic_id", label: "Mic id (bus key)", type: "string", default: "mic_default" },
      { name: "classes", label: "Classes", type: "strings",
         default: ["Glass", "Smoke", "Siren"],
         description: "YAMNet substrings (case-insensitive). E.g. Glass, Dog, Smoke, Siren, Speech." },
      { name: "min_score", label: "Min score", type: "number", default: 0.4, min: 0, max: 1 },
      { name: "cooldown_s", label: "Cooldown (s)", type: "number", default: 30, min: 1 },
      { name: "sink", label: "Notify via", type: "select",
         options: ["sink.ntfy", "sink.telegram", "sink.slack", "sink.home_assistant"],
         default: "sink.ntfy" },
    ],
    build: ({ mic_id, classes, min_score, cooldown_s, sink }, { id }) => {
      const src = id("source.audio"), yam = id("detector.audio_class"),
            cool = id("condition.cooldown"), snk = id(sink as string);
      return {
        nodes: [
          { id: src, type: "source.audio",
             config: { camera_id: mic_id, device: "default", sample_rate: 16000 } },
          { id: yam, type: "detector.audio_class",
             config: { min_score, top_k: 5, classes } },
          { id: cool, type: "condition.cooldown",
             config: { cooldown_s, scope: "per_camera_kind" } },
          { id: snk, type: sink as string, config: configForSink(sink as string) },
        ],
        edges: [
          { from: `${src}.audio`, to: `${yam}.audio` },
          { from: `${yam}.detections`, to: `${cool}.payload` },
          { from: `${cool}.match`, to: `${snk}.payload` },
        ],
      };
    },
  },
  {
    id: "privacy_stream",
    name: "Privacy-masked stream",
    description:
      "Detect faces, blur them, publish the masked frame as a dashboard tile.",
    category: "Privacy",
    fields: [
      { name: "camera", label: "Camera", type: "camera", required: true },
      { name: "method", label: "Method", type: "select",
         options: ["blur", "pixelate", "solid"], default: "blur" },
      { name: "label", label: "Stream label", type: "string", default: "Privacy" },
    ],
    build: ({ camera, method, label }, { id }) => {
      const src = id("source.camera"), face = id("detector.mediapipe"),
            mask = id("transform.privacy_mask"), out = id("broadcast.stream");
      return {
        nodes: [
          { id: src, type: "source.camera", config: { camera_id: camera } },
          { id: face, type: "detector.mediapipe", config: {} },
          { id: mask, type: "transform.privacy_mask",
             config: { mode: "detections", method, blur_kernel: 31 } },
          { id: out, type: "broadcast.stream", config: { label, fps: 15 } },
        ],
        edges: [
          { from: `${src}.frame`, to: `${face}.frame` },
          { from: `${face}.detections`, to: `${mask}.detections` },
          { from: `${src}.frame`, to: `${mask}.frame` },
          { from: `${mask}.frame`, to: `${out}.frame` },
        ],
      };
    },
  },
  {
    id: "depth_distance",
    name: "Depth distance trigger",
    description:
      "Detect + enrich with depth + fire when something is closer than N metres.",
    category: "Depth",
    fields: [
      { name: "camera", label: "Depth camera", type: "camera", required: true,
         description: "A depth-capable camera (Kinect / OAK-D / RealSense)" },
      { name: "max_distance_m", label: "Max distance (m)", type: "number", default: 1.5, min: 0.1, max: 10 },
      { name: "classes", label: "Classes", type: "strings", default: ["person"] },
      { name: "sink", label: "Notify via", type: "select",
         options: ["sink.ntfy", "sink.telegram", "sink.slack", "sink.home_assistant"],
         default: "sink.ntfy" },
    ],
    build: ({ camera, max_distance_m, classes, sink }, { id }) => {
      const rgb = id("source.camera"), depth = id("source.camera_depth"),
            yolo = id("detector.yolo"), enrich = id("transform.enrich_with_depth"),
            gate = id("condition.distance_gate"), cool = id("condition.cooldown"),
            snk = id(sink as string);
      return {
        nodes: [
          { id: rgb, type: "source.camera", config: { camera_id: camera } },
          { id: depth, type: "source.camera_depth", config: { camera_id: camera } },
          { id: yolo, type: "detector.yolo", config: { classes, conf: 0.4 } },
          { id: enrich, type: "transform.enrich_with_depth", config: { sample_window: 5 } },
          { id: gate, type: "condition.distance_gate",
             config: { max_distance_m, attr: "depth_m" } },
          { id: cool, type: "condition.cooldown",
             config: { cooldown_s: 30, scope: "per_camera" } },
          { id: snk, type: sink as string, config: configForSink(sink as string) },
        ],
        edges: [
          { from: `${rgb}.frame`, to: `${yolo}.frame` },
          { from: `${yolo}.detections`, to: `${enrich}.detections` },
          { from: `${depth}.depth`, to: `${enrich}.depth` },
          { from: `${enrich}.detections`, to: `${gate}.detections` },
          { from: `${gate}.match`, to: `${cool}.payload` },
          { from: `${cool}.match`, to: `${snk}.payload` },
        ],
      };
    },
  },
  {
    id: "fall_detection",
    name: "Fall detection (pose)",
    description:
      "MediaPipe pose + fall heuristic on hip-to-shoulder collapse → notify.",
    category: "Detect",
    fields: [
      { name: "camera", label: "Camera", type: "camera", required: true },
      { name: "cooldown_s", label: "Cooldown (s)", type: "number", default: 60, min: 1 },
      { name: "sink", label: "Notify via", type: "select",
         options: ["sink.ntfy", "sink.telegram", "sink.slack", "sink.home_assistant"],
         default: "sink.ntfy" },
    ],
    build: ({ camera, cooldown_s, sink }, { id }) => {
      const src = id("source.camera"), pose = id("detector.pose"),
            fall = id("condition.fall_detection"), cool = id("condition.cooldown"),
            snk = id(sink as string);
      return {
        nodes: [
          { id: src, type: "source.camera", config: { camera_id: camera } },
          { id: pose, type: "detector.pose", config: {} },
          { id: fall, type: "condition.fall_detection", config: {} },
          { id: cool, type: "condition.cooldown",
             config: { cooldown_s, scope: "per_camera" } },
          { id: snk, type: sink as string, config: configForSink(sink as string) },
        ],
        edges: [
          { from: `${src}.frame`, to: `${pose}.frame` },
          { from: `${pose}.detections`, to: `${fall}.detections` },
          { from: `${fall}.match`, to: `${cool}.payload` },
          { from: `${cool}.match`, to: `${snk}.payload` },
        ],
      };
    },
  },
  {
    id: "reid_pair",
    name: "Cross-camera Re-ID pair",
    description:
      "Two cameras with shared track ids — same person walking between them keeps id=N.",
    category: "Multi-camera",
    fields: [
      { name: "camera_a", label: "Camera A", type: "camera", required: true },
      { name: "camera_b", label: "Camera B", type: "camera", required: true },
    ],
    build: ({ camera_a, camera_b }, { id }) => {
      const sa = id("source.camera"), sb = id("source.camera"),
            ya = id("detector.yolo"), yb = id("detector.yolo"),
            ra = id("transform.reid"), rb = id("transform.reid"),
            aa = id("transform.annotate"), ab = id("transform.annotate"),
            oa = id("broadcast.stream"), ob = id("broadcast.stream");
      const yconf = { classes: ["person"], conf: 0.45 };
      const rcfg = { backend: "auto", similarity_threshold: 0.78, history_seconds: 60 };
      return {
        nodes: [
          { id: sa, type: "source.camera", config: { camera_id: camera_a } },
          { id: sb, type: "source.camera", config: { camera_id: camera_b } },
          { id: ya, type: "detector.yolo", config: yconf },
          { id: yb, type: "detector.yolo", config: yconf },
          { id: ra, type: "transform.reid", config: rcfg },
          { id: rb, type: "transform.reid", config: rcfg },
          { id: aa, type: "transform.annotate",
             config: { label_format: "id={track_id} {label}" } },
          { id: ab, type: "transform.annotate",
             config: { label_format: "id={track_id} {label}" } },
          { id: oa, type: "broadcast.stream", config: { label: "A · Re-ID", fps: 10 } },
          { id: ob, type: "broadcast.stream", config: { label: "B · Re-ID", fps: 10 } },
        ],
        edges: [
          { from: `${sa}.frame`, to: `${ya}.frame` },
          { from: `${sb}.frame`, to: `${yb}.frame` },
          { from: `${ya}.detections`, to: `${ra}.detections` },
          { from: `${yb}.detections`, to: `${rb}.detections` },
          { from: `${sa}.frame`, to: `${ra}.frame` },
          { from: `${sb}.frame`, to: `${rb}.frame` },
          { from: `${ra}.detections`, to: `${aa}.detections` },
          { from: `${rb}.detections`, to: `${ab}.detections` },
          { from: `${sa}.frame`, to: `${aa}.frame` },
          { from: `${sb}.frame`, to: `${ab}.frame` },
          { from: `${aa}.frame`, to: `${oa}.frame` },
          { from: `${ab}.frame`, to: `${ob}.frame` },
        ],
      };
    },
  },
];

function configForSink(sinkType: string): Record<string, unknown> {
  switch (sinkType) {
    case "sink.ntfy":
      return { topic: "camera_dash_alerts", priority: 4 };
    case "sink.telegram":
      return { template: "{kind} on {camera_id} — {summary}" };
    case "sink.slack":
      return { webhook_url_env: "SLACK_WEBHOOK_URL" };
    case "sink.home_assistant":
      return {
        url_env: "HOME_ASSISTANT_URL", token_env: "HOME_ASSISTANT_TOKEN",
        entity_id: "REPLACE_ME", action: "on", cooldown_s: 60,
      };
    case "sink.email":
      return { to_addrs: ["REPLACE_ME@example.com"], subject_template: "{kind}: {camera_id}" };
    default:
      return {};
  }
}
