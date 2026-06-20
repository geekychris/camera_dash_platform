import { useEffect, useState } from "react";
import { Rnd } from "react-rnd";
import { api, CameraInfo, DerivedStream, SnapshotInfo, Tile } from "../api/client";
import CameraTile from "./CameraTile";
import LogTile, { LogConfig } from "./LogTile";
import AlertTile, { AlertConfig } from "./AlertTile";
import PointCloudTile from "./PointCloudTile";
import SnapshotTile from "./SnapshotTile";
import StatsTile from "./StatsTile";
import TimelineTile from "./TimelineTile";

const STORAGE_KEY = "camera_dash.layout.v3";

type Box = { x: number; y: number; w: number; h: number };
type StoredLog = { box: Box; config: LogConfig };
type StoredAlert = { box: Box; config: AlertConfig };
type StoredStats = { box: Box };

type Stored = {
  boxes: Record<string, Box>;
  logs: Record<string, StoredLog>;
  alerts: Record<string, StoredAlert>;
  stats: Record<string, StoredStats>;
  timelines: Record<string, StoredStats>;
};

const SEEDED_KEY = "camera_dash.layout.v3.seeded";

function loadStored(): Stored {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    const stored: Stored = {
      boxes: raw.boxes || {},
      logs: raw.logs || {},
      alerts: raw.alerts || {},
      stats: raw.stats || {},
      timelines: raw.timelines || {},
    };
    if (!localStorage.getItem(SEEDED_KEY) && Object.keys(stored.logs).length === 0) {
      stored.logs["log:seed"] = {
        box: { x: 32, y: 32, w: 520, h: 360 },
        config: { label: "events", pipelineFilter: "", kindFilter: "" },
      };
      localStorage.setItem(SEEDED_KEY, "1");
    }
    return stored;
  } catch {
    return { boxes: {}, logs: {}, alerts: {}, stats: {}, timelines: {} };
  }
}

export default function Dashboard() {
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [stored, setStored] = useState<Stored>(() => loadStored());

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      const [cams, streams, snaps] = await Promise.all([
        api.listCameras().catch(() => [] as CameraInfo[]),
        api.listStreams().catch(() => [] as DerivedStream[]),
        api.listSnapshots().catch(() => [] as SnapshotInfo[]),
      ]);
      if (cancelled) return;
      // Depth cameras get an extra 3D tile alongside the 2D RGB tile so
      // users see both views by default. The tile id is the camera id with
      // a `:3d` suffix to keep its layout box separate from the RGB tile's.
      const depthCams: Tile[] = cams
        .filter((c) => c.has_depth)
        .map((c): Tile => ({
          kind: "pointcloud",
          data: { ...c, id: `${c.id}:3d` },
        }));
      setTiles([
        ...cams.map((c): Tile => ({ kind: "camera", data: c })),
        ...depthCams,
        ...streams.map((s): Tile => ({ kind: "derived", data: s })),
        ...snaps.map((s): Tile => ({ kind: "snapshot", data: s })),
      ]);
    }
    refresh();
    const t = setInterval(refresh, 5000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  // Default-place new camera/derived tiles + drop vanished ones.
  useEffect(() => {
    setStored((prev) => {
      const boxes = { ...prev.boxes };
      let i = Object.keys(boxes).length;
      for (const t of tiles) {
        if (!boxes[t.data.id]) {
          boxes[t.data.id] = {
            x: (i % 2) * 660 + 16,
            y: Math.floor(i / 2) * 520 + 16,
            w: 640,
            h: 500,
          };
          i++;
        }
      }
      for (const id of Object.keys(boxes)) {
        if (!tiles.some((t) => t.data.id === id)) delete boxes[id];
      }
      const next = { ...prev, boxes };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, [tiles]);

  function persist(updater: (s: Stored) => Stored) {
    setStored((prev) => {
      const next = updater(prev);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }

  function moveOrResize(id: string, box: Box) {
    persist((s) => {
      if (s.boxes[id]) return { ...s, boxes: { ...s.boxes, [id]: box } };
      if (s.logs[id]) return { ...s, logs: { ...s.logs, [id]: { ...s.logs[id], box } } };
      if (s.alerts[id]) return { ...s, alerts: { ...s.alerts, [id]: { ...s.alerts[id], box } } };
      if (s.stats[id]) return { ...s, stats: { ...s.stats, [id]: { ...s.stats[id], box } } };
      if (s.timelines[id]) return { ...s, timelines: { ...s.timelines, [id]: { ...s.timelines[id], box } } };
      return s;
    });
  }

  function addLogTile() {
    const uid = `log:${Math.random().toString(36).slice(2, 9)}`;
    persist((s) => ({
      ...s,
      logs: {
        ...s.logs,
        [uid]: {
          box: { x: 32, y: 32, w: 520, h: 360 },
          config: { label: "events", pipelineFilter: "", kindFilter: "" },
        },
      },
    }));
  }

  function addAlertTile() {
    const uid = `alert:${Math.random().toString(36).slice(2, 9)}`;
    persist((s) => ({
      ...s,
      alerts: {
        ...s.alerts,
        [uid]: {
          box: { x: 64, y: 64, w: 520, h: 320 },
          config: { label: "alerts", sound: false, flashMs: 800 },
        },
      },
    }));
  }

  function addStatsTile() {
    const uid = `stats:${Math.random().toString(36).slice(2, 9)}`;
    persist((s) => ({
      ...s,
      stats: { ...s.stats, [uid]: { box: { x: 96, y: 96, w: 360, h: 400 } } },
    }));
  }

  function updateLogConfig(uid: string, config: LogConfig) {
    persist((s) =>
      s.logs[uid] ? { ...s, logs: { ...s.logs, [uid]: { ...s.logs[uid], config } } } : s,
    );
  }

  function updateAlertConfig(uid: string, config: AlertConfig) {
    persist((s) =>
      s.alerts[uid] ? { ...s, alerts: { ...s.alerts, [uid]: { ...s.alerts[uid], config } } } : s,
    );
  }

  function removeLogTile(uid: string) {
    persist((s) => { const n = { ...s.logs }; delete n[uid]; return { ...s, logs: n }; });
  }
  function removeAlertTile(uid: string) {
    persist((s) => { const n = { ...s.alerts }; delete n[uid]; return { ...s, alerts: n }; });
  }
  function removeStatsTile(uid: string) {
    persist((s) => { const n = { ...s.stats }; delete n[uid]; return { ...s, stats: n }; });
  }

  function addTimelineTile() {
    const uid = `timeline:${Math.random().toString(36).slice(2, 9)}`;
    persist((s) => ({
      ...s,
      timelines: { ...s.timelines, [uid]: { box: { x: 128, y: 128, w: 720, h: 280 } } },
    }));
  }
  function removeTimelineTile(uid: string) {
    persist((s) => { const n = { ...s.timelines }; delete n[uid]; return { ...s, timelines: n }; });
  }

  function resetLayout() {
    localStorage.removeItem(STORAGE_KEY);
    setStored({ boxes: {}, logs: {}, alerts: {}, stats: {}, timelines: {} });
  }

  return (
    <div className="relative h-full overflow-auto bg-slate-950">
      <div className="sticky top-0 z-50 flex items-center justify-between gap-3 border-b border-slate-800 bg-slate-900/90 px-3 py-1 text-xs backdrop-blur">
        <span className="text-slate-400">
          Drag the title bar to move · drag any edge or corner to resize · scroll on video to zoom
        </span>
        <span className="flex items-center gap-2">
          <button
            onClick={addLogTile}
            className="rounded border border-amber-700 px-2 py-0.5 text-amber-300 hover:bg-amber-900/40"
          >+ Log</button>
          <button
            onClick={addAlertTile}
            className="rounded border border-rose-700 px-2 py-0.5 text-rose-300 hover:bg-rose-900/40"
          >+ Alert</button>
          <button
            onClick={addStatsTile}
            className="rounded border border-emerald-700 px-2 py-0.5 text-emerald-300 hover:bg-emerald-900/40"
          >+ Stats</button>
          <button
            onClick={addTimelineTile}
            className="rounded border border-cyan-700 px-2 py-0.5 text-cyan-300 hover:bg-cyan-900/40"
          >+ Timeline</button>
          <button
            onClick={resetLayout}
            className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800"
          >Reset layout</button>
        </span>
      </div>

      {tiles.length === 0 && Object.keys(stored.logs).length === 0 && (
        <div className="p-8 text-center text-slate-400">
          No cameras, streams, or log tiles yet. Add a camera in{" "}
          <a href="/cameras" className="underline">Cameras</a>, compose a pipeline in{" "}
          <a href="/editor" className="underline">Pipelines</a>, or click{" "}
          <span className="text-amber-300">+ Log</span> above for an event console.
        </div>
      )}

      <div className="relative" style={{ minHeight: "calc(100vh - 80px)" }}>
        {tiles.map((t) =>
          renderRnd(
            t.data.id,
            stored.boxes[t.data.id],
            moveOrResize,
            t.kind === "camera"
              ? <CameraTile camera={t.data} />
              : t.kind === "derived"
                ? <CameraTile camera={derivedToCameraShim(t.data)} badge="derived" pipelineId={t.data.pipeline_id} sourceCameraId={t.data.source_camera_id} />
                : t.kind === "pointcloud"
                  ? <PointCloudTile camera={t.data} />
                  : <SnapshotTile info={t.data} />,
          ),
        )}
        {Object.entries(stored.logs).map(([uid, entry]) =>
          renderRnd(
            uid,
            entry.box,
            moveOrResize,
            <LogTile
              config={entry.config}
              onConfigChange={(c) => updateLogConfig(uid, c)}
              onRemove={() => removeLogTile(uid)}
            />,
          ),
        )}
        {Object.entries(stored.alerts).map(([uid, entry]) =>
          renderRnd(
            uid,
            entry.box,
            moveOrResize,
            <AlertTile
              config={entry.config}
              onConfigChange={(c) => updateAlertConfig(uid, c)}
              onRemove={() => removeAlertTile(uid)}
            />,
          ),
        )}
        {Object.entries(stored.stats).map(([uid, entry]) =>
          renderRnd(uid, entry.box, moveOrResize, <StatsTile onRemove={() => removeStatsTile(uid)} />),
        )}
        {Object.entries(stored.timelines).map(([uid, entry]) =>
          renderRnd(uid, entry.box, moveOrResize, <TimelineTile onRemove={() => removeTimelineTile(uid)} />),
        )}
      </div>
    </div>
  );
}

function renderRnd(
  key: string,
  box: Box | undefined,
  onChange: (id: string, box: Box) => void,
  children: React.ReactNode,
) {
  if (!box) return null;
  return (
    <Rnd
      key={key}
      position={{ x: box.x, y: box.y }}
      size={{ width: box.w, height: box.h }}
      minWidth={240}
      minHeight={180}
      bounds="parent"
      dragHandleClassName="drag-handle"
      enableResizing={{
        top: true, right: true, bottom: true, left: true,
        topRight: true, bottomRight: true, bottomLeft: true, topLeft: true,
      }}
      onDragStop={(_e, d) => onChange(key, { ...box, x: d.x, y: d.y })}
      onResizeStop={(_e, _dir, ref, _delta, pos) =>
        onChange(key, {
          x: pos.x,
          y: pos.y,
          w: parseInt(ref.style.width),
          h: parseInt(ref.style.height),
        })
      }
      className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900 shadow-lg"
      style={{ zIndex: 1 }}
    >
      {children}
    </Rnd>
  );
}

function derivedToCameraShim(s: DerivedStream): CameraInfo {
  return {
    id: s.id,
    kind: `derived (${s.node_id})`,
    label: s.label,
    params: { width: s.width, height: s.height, fps: s.fps },
    running: true,
    is_thermal: false,
    urls: s.urls,
  };
}
