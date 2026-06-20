import React from "react";
import { Edge, Node } from "@xyflow/react";

type Cfg = Record<string, unknown>;

function cfg(n: Node): Cfg {
  return ((n.data as { config?: Cfg })?.config) || {};
}

function ntype(n: Node): string {
  return ((n.data as { type?: string })?.type) || "";
}

/**
 * Layered left-to-right layout. Roots (no incoming edges) go in column 0;
 * every other node's column = 1 + max(parent column). Rows are assigned
 * top-to-bottom within each column. Suitable for the small DAGs the editor
 * produces — no external graph library required.
 */
export function layoutGraph(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return nodes;

  const parents = new Map<string, string[]>();
  nodes.forEach((n) => parents.set(n.id, []));
  edges.forEach((e) => {
    const arr = parents.get(e.target);
    if (arr) arr.push(e.source);
  });

  const col = new Map<string, number>();

  function depth(id: string, seen: Set<string>): number {
    const cached = col.get(id);
    if (cached !== undefined) return cached;
    if (seen.has(id)) return 0;
    seen.add(id);
    const ps = parents.get(id) || [];
    const d = ps.length === 0 ? 0 : Math.max(...ps.map((p) => depth(p, seen) + 1));
    col.set(id, d);
    return d;
  }
  nodes.forEach((n) => depth(n.id, new Set()));

  const byCol = new Map<number, string[]>();
  nodes.forEach((n) => {
    const c = col.get(n.id) ?? 0;
    if (!byCol.has(c)) byCol.set(c, []);
    byCol.get(c)!.push(n.id);
  });

  const colW = 240;
  const rowH = 140;
  const pos = new Map<string, { x: number; y: number }>();
  byCol.forEach((ids, c) => {
    ids.forEach((id, r) => pos.set(id, { x: c * colW, y: r * rowH }));
  });

  return nodes.map((n) => ({ ...n, position: pos.get(n.id) ?? n.position }));
}

/**
 * Topological sort. Nodes with cycles fall to the end in input order — we
 * don't refuse to render an invalid graph, we just describe what we can.
 */
function topoOrder(nodes: Node[], edges: Edge[]): Node[] {
  const indeg = new Map<string, number>();
  const out = new Map<string, string[]>();
  nodes.forEach((n) => {
    indeg.set(n.id, 0);
    out.set(n.id, []);
  });
  edges.forEach((e) => {
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1);
    out.get(e.source)?.push(e.target);
  });
  const queue = nodes.filter((n) => (indeg.get(n.id) ?? 0) === 0).map((n) => n.id);
  const order: string[] = [];
  while (queue.length) {
    const id = queue.shift()!;
    order.push(id);
    (out.get(id) ?? []).forEach((t) => {
      indeg.set(t, (indeg.get(t) ?? 1) - 1);
      if (indeg.get(t) === 0) queue.push(t);
    });
  }
  const seen = new Set(order);
  nodes.forEach((n) => { if (!seen.has(n.id)) order.push(n.id); });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return order.map((id) => byId.get(id)!).filter(Boolean);
}

function fmtList(items: unknown): string {
  if (!Array.isArray(items)) return String(items ?? "");
  if (items.length === 0) return "";
  if (items.length === 1) return `"${items[0]}"`;
  if (items.length <= 4) return items.map((s) => `"${s}"`).join(", ");
  return `${items.slice(0, 3).map((s) => `"${s}"`).join(", ")} (+${items.length - 3} more)`;
}

function describeNode(n: Node): string | null {
  const t = ntype(n);
  const c = cfg(n);

  switch (t) {
    case "source.camera":
      return `Reads frames from camera **${c.camera_id || "?"}**`;
    case "source.file":
      return `Reads frames from file \`${c.path || "?"}\`${c.fps ? ` at ${c.fps} fps` : ""}`;

    case "transform.frame_sample":
      return `samples to **${c.target_fps ?? 2} fps**`;
    case "transform.resize":
      return `resizes to ${c.width || "?"}×${c.height || "?"}`;
    case "transform.crop":
      return `crops to a region of interest`;
    case "transform.colormap":
      return `applies the **${c.colormap || "default"}** colormap`;
    case "transform.annotate":
      return `draws bounding boxes on each frame`;
    case "transform.throttle":
      return `forwards events at most every **${c.interval_s ?? 5}s**`;
    case "transform.tracker":
      return `tracks detections across frames (ByteTrack)`;
    case "transform.privacy_mask":
      return `blurs configured regions`;

    case "detector.yolo": {
      const classes = c.classes ? fmtList(c.classes) : "COCO classes";
      return `runs **YOLO** (\`${c.model || "yolov8n.pt"}\`, conf ≥ ${c.conf ?? 0.25}) for ${classes}`;
    }
    case "detector.yolo_world": {
      const classes = c.classes ? fmtList(c.classes) : "(no classes set)";
      return `runs **YOLO-World** open-vocab (\`${c.model || "yolov8s-worldv2.pt"}\`, conf ≥ ${c.conf ?? 0.1}${c.imgsz ? `, imgsz ${c.imgsz}` : ""}) for ${classes}`;
    }
    case "detector.onnx":
      return `runs an ONNX detector (\`${c.model_path || "?"}\`)`;
    case "detector.opencv_dnn":
      return `runs an OpenCV DNN detector`;
    case "detector.mediapipe":
      return `runs MediaPipe face detection`;
    case "detector.mog2":
      return `detects motion (MOG2 background subtraction)`;
    case "detector.optical_flow":
      return `detects motion via optical flow`;
    case "detector.vision_llm":
      return `asks a vision-LLM (\`${c.model || "?"}\`) at most every ${c.interval_s ?? 30}s`;
    case "detector.pose":
      return `estimates human poses`;
    case "detector.segmentation":
      return `runs instance segmentation`;
    case "detector.ocr":
      return `runs OCR on each frame`;
    case "detector.anomaly":
      return `flags anomalies vs. a learned baseline`;

    case "condition.metadata_match":
      return `gates on metadata matching ${JSON.stringify(c.match || {})}`;
    case "condition.temperature_gate":
      return `gates when temperature crosses **${c.threshold_c ?? "?"}°C**`;
    case "condition.zone":
      return `gates on objects entering a polygon zone`;
    case "condition.counter":
      return `counts events and triggers on **${c.threshold ?? "?"}**`;
    case "condition.line_crossing":
      return `gates on objects crossing a line`;
    case "condition.schedule":
      return `gates by time-of-day schedule`;
    case "condition.cooldown":
      return `suppresses repeat events within **${c.cooldown_s ?? "?"}s**`;

    case "sink.stream":
    case "broadcast.stream":
      return `publishes annotated video to a derived stream (${c.fps ?? 10} fps)`;
    case "broadcast.snapshot":
      return `serves the latest frame as a JPEG at /api/broadcast/snapshot/${c.id ?? "<pipeline>/<node>"}.jpg`;
    case "sink.console":
      return `logs to console (\`${c.level || "info"}\`)`;
    case "sink.jsonl":
      return `appends events as JSONL to \`${c.path || "data/events/<pipeline>.jsonl"}\``;
    case "sink.slack":
      return `posts matched events to a Slack incoming webhook`;
    case "sink.mqtt":
      return `publishes to MQTT topic **\`${c.topic || "?"}\`**`;
    case "sink.kafka":
      return `publishes to Kafka topic **\`${c.topic || "?"}\`**`;
    case "sink.webhook":
      return `POSTs to **\`${c.url || "?"}\`**`;
    case "sink.recorder":
      return `records clips to disk`;
    case "sink.sqlite":
      return `persists events to SQLite`;
    case "sink.email":
      return `sends email to **\`${c.to || "?"}\`**`;
    case "sink.ntfy":
      return `pushes to ntfy topic **\`${c.topic || "?"}\`**`;
    case "sink.pushover":
      return `sends Pushover notifications`;
    case "sink.telegram":
      return `sends Telegram messages`;
  }
  return `runs \`${t}\``;
}

/**
 * Markdown-flavored, one-paragraph summary of what the current graph does.
 * Renders directly with simple `**bold**` / `` `code` `` substitution so we
 * don't need a Markdown library.
 */
export function describeGraph(nodes: Node[], edges: Edge[]): string {
  if (nodes.length === 0) return "_Add a source node to get started._";
  const ordered = topoOrder(nodes, edges);
  const parts = ordered.map(describeNode).filter((s): s is string => Boolean(s));
  if (parts.length === 0) return "_(empty pipeline)_";
  const head = parts[0];
  const rest = parts.slice(1);
  if (rest.length === 0) return head + ".";
  return head + ", then " + rest.join(", then ") + ".";
}

const BOLD = /\*\*(.+?)\*\*/g;
const CODE = /`(.+?)`/g;

/**
 * Tiny renderer for the subset of Markdown describeGraph emits. Returns a
 * React fragment so the editor can render it without pulling in a Markdown lib.
 */
export function renderInlineMarkdown(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let key = 0;

  function pushSegment(seg: string) {
    const codeParts = seg.split(CODE);
    codeParts.forEach((part, i) => {
      if (i % 2 === 1) {
        out.push(<code key={key++} className="rounded bg-slate-800 px-1 text-amber-300">{part}</code>);
      } else if (part) {
        out.push(<span key={key++}>{part}</span>);
      }
    });
  }

  const boldParts = text.split(BOLD);
  boldParts.forEach((part, i) => {
    if (i % 2 === 1) {
      out.push(<strong key={key++} className="text-slate-100">{part}</strong>);
    } else if (part) {
      pushSegment(part);
    }
  });
  return out;
}
