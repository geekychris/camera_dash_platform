export type CameraInfo = {
  id: string;
  kind: string;
  label: string;
  params: Record<string, unknown>;
  running: boolean;
  is_thermal: boolean;
  has_depth?: boolean;
  urls: { webrtc: string; hls: string; rtsp: string };
};

export type DerivedStream = {
  id: string;
  pipeline_id: string;
  node_id: string;
  label: string;
  source_camera_id: string | null;
  width: number;
  height: number;
  fps: number;
  kind: "derived";
  urls: { webrtc: string; hls: string; rtsp: string };
};

export type SnapshotInfo = {
  id: string;
  pipeline_id: string;
  node_id: string;
  label: string;
  width: number;
  height: number;
  source_camera_id: string | null;
  updated_at: number;
  url: string;
};

export type Tile =
  | { kind: "camera"; data: CameraInfo }
  | { kind: "derived"; data: DerivedStream }
  | { kind: "snapshot"; data: SnapshotInfo };

export type PipelineDef = {
  id: string;
  name: string;
  definition: GraphJson;
  enabled: boolean;
};

export type GraphJson = {
  id: string;
  name?: string;
  nodes: { id: string; type: string; config: Record<string, unknown>; position?: { x: number; y: number } }[];
  edges: { from: string; to: string }[];
};

export type NodeDescriptor = {
  type_id: string;
  category: string;
  inputs: { name: string; port_type: string; required: boolean }[];
  outputs: { name: string; port_type: string; required: boolean }[];
  config_schema: Record<string, unknown>;
  doc: string;
};

const API = "/api";

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

export const api = {
  // cameras
  listCameras: () => fetch(`${API}/cameras`).then(jsonOrThrow<CameraInfo[]>),
  listStreams: () => fetch(`${API}/streams`).then(jsonOrThrow<DerivedStream[]>),
  listSnapshots: () => fetch(`${API}/broadcast/snapshot`).then(jsonOrThrow<SnapshotInfo[]>),
  discoverCameras: () => fetch(`${API}/cameras/discover`).then(jsonOrThrow<{
    uvc: { index: number; name: string; device?: string }[];
    kinect?: { index: number; name: string; serial?: string }[];
  }>),
  addCamera: (c: Omit<CameraInfo, "running" | "is_thermal" | "urls"> & { enabled?: boolean }) =>
    fetch(`${API}/cameras`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled: true, ...c }) }).then(jsonOrThrow<CameraInfo>),
  removeCamera: (id: string) => fetch(`${API}/cameras/${id}`, { method: "DELETE" }),
  setLabel: (id: string, label: string) =>
    fetch(`${API}/cameras/${id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ label }) }).then(jsonOrThrow<CameraInfo>),

  // snapshots
  snapshot: (cameraId: string) =>
    fetch(`${API}/snapshots/${cameraId}`, { method: "POST" }).then(jsonOrThrow<{ id: string; path: string }>),

  // per-camera restart — used after a hardware replug to drop the driver's stale handle
  restartCamera: (cameraId: string) =>
    fetch(`${API}/cameras/${cameraId}/restart`, { method: "POST" }).then(jsonOrThrow<CameraInfo>),

  // templates + draft (AI composer)
  listTemplates: () => fetch(`${API}/templates`).then(
    jsonOrThrow<{ id: string; name: string; description?: string; definition: GraphJson }[]>),
  listExamples: () => fetch(`${API}/examples`).then(
    jsonOrThrow<{
      id: string; name: string; description: string; use_case: string;
      tags: string[]; complexity: string; requires_env: string[];
      placeholders: string[]; definition: GraphJson;
    }[]>),
  installExample: (exampleId: string, opts: { camera_map?: Record<string, string>; target_id?: string; enabled?: boolean } = {}) =>
    fetch(`${API}/examples/${exampleId}/install`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ camera_map: {}, enabled: false, ...opts }),
    }).then(jsonOrThrow<{ id: string; installed: boolean; started: boolean }>),
  draftPipeline: (prompt: string, opts: { pipeline_id?: string; cameras_hint?: string[] } = {}) =>
    fetch(`${API}/draft`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt, ...opts }),
    }).then(jsonOrThrow<{ definition: GraphJson; valid: boolean; error?: string; raw_model_output?: string }>),

  // clips
  clipThumbUrl: (id: string) => `${API}/clips/${id}/thumb`,
  listClips: (params: { camera_id?: string; pipeline_id?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && q.set(k, String(v)));
    return fetch(`${API}/clips?${q}`).then(
      jsonOrThrow<{ id: string; camera_id: string; pipeline_id: string | null; started_at: string;
                    ended_at: string | null; trigger: unknown; size_bytes: number; exists: boolean }[]>);
  },
  clipFileUrl: (id: string) => `${API}/clips/${id}/file`,
  deleteClip: (id: string) => fetch(`${API}/clips/${id}`, { method: "DELETE" }),

  // stats
  stats: () => fetch(`${API}/stats`).then(
    jsonOrThrow<{
      cameras: { id: string; label: string; kind: string; running: boolean; fps: number; subscribers: number }[];
      derived: { id: string; label: string; fps: number; subscribers: number }[];
      pipelines: Record<string, { id: string; nodes: { id: string; type: string }[]; running: number }>;
    }>),

  // pipelines
  listPipelines: () => fetch(`${API}/pipelines`).then(jsonOrThrow<PipelineDef[]>),
  getPipeline: (id: string) => fetch(`${API}/pipelines/${id}`).then(jsonOrThrow<PipelineDef>),
  savePipeline: (p: PipelineDef) =>
    fetch(`${API}/pipelines/${p.id}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(p) }).then(jsonOrThrow<PipelineDef>),
  deletePipeline: (id: string) => fetch(`${API}/pipelines/${id}`, { method: "DELETE" }),
  startPipeline: (id: string) => fetch(`${API}/pipelines/${id}/start`, { method: "POST" }).then(jsonOrThrow<PipelineDef>),
  stopPipeline: (id: string) => fetch(`${API}/pipelines/${id}/stop`, { method: "POST" }).then(jsonOrThrow<PipelineDef>),
  pipelineStatus: () => fetch(`${API}/pipelines/status`).then(jsonOrThrow<Record<string, unknown>>),
  pipelineSourceCameras: (id: string) =>
    fetch(`${API}/pipelines/${id}/source-cameras`).then(jsonOrThrow<string[]>),
  clonePipeline: (
    id: string,
    body: { new_id: string; name?: string; camera_map?: Record<string, string>; enabled?: boolean },
  ) => fetch(`${API}/pipelines/${id}/clone`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  }).then(jsonOrThrow<PipelineDef>),

  // plugins
  catalog: () => fetch(`${API}/plugins`).then(jsonOrThrow<{ nodes: NodeDescriptor[] }>),

  // events SSE
  eventStream(onEvent: (e: { kind: string; payload: unknown; camera_id: string; pipeline_id: string }) => void) {
    const es = new EventSource(`${API}/events/stream`);
    es.addEventListener("event", (e) => onEvent(JSON.parse((e as MessageEvent).data)));
    return es;
  },

  // historical events
  listEvents: (params: { pipeline_id?: string; camera_id?: string; kind?: string; limit?: number }) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && q.set(k, String(v)));
    return fetch(`${API}/events?${q}`).then(jsonOrThrow<{ id: number; pipeline_id: string; camera_id: string | null; timestamp: string; kind: string; payload: unknown }[]>);
  },
};

// WHEP client: WebRTC from MediaMTX
export async function whepConnect(url: string, video: HTMLVideoElement): Promise<RTCPeerConnection> {
  const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });
  pc.ontrack = (e) => {
    video.srcObject = e.streams[0];
    video.play().catch(() => {});
  };
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  const r = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/sdp" },
    body: offer.sdp,
  });
  if (!r.ok) throw new Error(`WHEP failed: ${r.status}`);
  const answer = await r.text();
  await pc.setRemoteDescription({ type: "answer", sdp: answer });
  return pc;
}

// Radiometric WS: returns a teardown function
export function radiometricSubscribe(
  cameraId: string,
  onFrame: (w: number, h: number, data: Uint16Array) => void,
): () => void {
  return _binaryMatrixSubscribe(`/api/radiometric/${cameraId}`, onFrame);
}

// Depth WS: same wire format as radiometric, but the matrix is millimetres
// (uint16, 0 = invalid). Returns a teardown function.
export function depthSubscribe(
  cameraId: string,
  onFrame: (w: number, h: number, data: Uint16Array) => void,
): () => void {
  return _binaryMatrixSubscribe(`/api/depth/${cameraId}`, onFrame);
}

function _binaryMatrixSubscribe(
  path: string,
  onFrame: (w: number, h: number, data: Uint16Array) => void,
): () => void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}${path}`);
  ws.binaryType = "arraybuffer";
  ws.onmessage = (ev) => {
    const buf = ev.data as ArrayBuffer;
    const dv = new DataView(buf);
    const w = dv.getUint16(0, true);
    const h = dv.getUint16(2, true);
    const data = new Uint16Array(buf, 4, w * h);
    onFrame(w, h, data);
  };
  return () => ws.close();
}
