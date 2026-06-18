import { useEffect, useState } from "react";
import { api } from "../api/client";

type Clip = {
  id: string;
  camera_id: string;
  pipeline_id: string | null;
  started_at: string;
  ended_at: string | null;
  trigger: unknown;
  size_bytes: number;
  exists: boolean;
  thumb?: boolean;
  is_image?: boolean;
};

type ViewMode = "grid" | "list";

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export default function ClipsBrowser() {
  const [clips, setClips] = useState<Clip[]>([]);
  const [selected, setSelected] = useState<Clip | null>(null);
  const [cameraFilter, setCameraFilter] = useState<string>("");
  const [pipelineFilter, setPipelineFilter] = useState<string>("");
  const [view, setView] = useState<ViewMode>(() =>
    (localStorage.getItem("camera_dash.clips.view") as ViewMode) || "grid");

  async function refresh() {
    const params: Record<string, string | number> = { limit: 200 };
    if (cameraFilter) params.camera_id = cameraFilter;
    if (pipelineFilter) params.pipeline_id = pipelineFilter;
    setClips(await api.listClips(params));
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, [cameraFilter, pipelineFilter]);

  async function remove(c: Clip) {
    if (!confirm(`Delete clip ${c.id}?`)) return;
    await api.deleteClip(c.id);
    if (selected?.id === c.id) setSelected(null);
    refresh();
  }

  return (
    <div className="flex h-full">
      <div className="flex w-1/2 min-w-0 flex-col border-r border-slate-800">
        <div className="flex shrink-0 items-center gap-2 border-b border-slate-800 bg-slate-900 px-3 py-2 text-xs">
          <span className="text-slate-400">Clips</span>
          <input
            placeholder="camera filter"
            className="rounded bg-slate-950 px-2 py-0.5"
            value={cameraFilter}
            onChange={(e) => setCameraFilter(e.target.value)}
          />
          <input
            placeholder="pipeline filter"
            className="rounded bg-slate-950 px-2 py-0.5"
            value={pipelineFilter}
            onChange={(e) => setPipelineFilter(e.target.value)}
          />
          <button
            onClick={refresh}
            className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800"
          >Refresh</button>
          <span className="ml-auto flex items-center gap-2 text-slate-500">
            <span>{clips.length} clip(s)</span>
            <button
              onClick={() => { const v = view === "grid" ? "list" : "grid"; setView(v); localStorage.setItem("camera_dash.clips.view", v); }}
              className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800"
            >{view === "grid" ? "List" : "Grid"}</button>
          </span>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {clips.length === 0 && (
            <div className="p-6 text-center text-slate-500">
              No clips yet. They get written when a pipeline ending in
              <code className="mx-1 rounded bg-slate-800 px-1">sink.recorder</code>
              fires a trigger. Or click 📷 on a camera tile for a snapshot.
            </div>
          )}
          {view === "grid" && clips.length > 0 && (
            <div className="grid grid-cols-2 gap-2 p-2 sm:grid-cols-3">
              {clips.map((c) => {
                const isSnap = !!c.is_image;
                return (
                  <button
                    key={c.id}
                    onClick={() => setSelected(c)}
                    className={`group relative aspect-video overflow-hidden rounded border ${
                      selected?.id === c.id ? "border-cyan-400" : "border-slate-800"
                    } bg-black hover:border-slate-500`}
                  >
                    {(c.thumb || isSnap) ? (
                      <img
                        src={isSnap ? api.clipFileUrl(c.id) : api.clipThumbUrl(c.id)}
                        alt=""
                        className="h-full w-full object-cover"
                        loading="lazy"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center text-slate-600">📹</div>
                    )}
                    <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-1 text-left text-[10px] text-slate-200">
                      <div className="truncate">{c.camera_id} {isSnap && "📷"}</div>
                      <div className="truncate text-slate-400">
                        {new Date(c.started_at).toLocaleString()}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
          {view === "list" && (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-900 text-left text-slate-400">
              <tr>
                <th className="px-2 py-2">When</th>
                <th className="px-2">Camera</th>
                <th className="px-2">Pipeline</th>
                <th className="px-2">Size</th>
                <th className="px-2"></th>
              </tr>
            </thead>
            <tbody>
              {clips.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => setSelected(c)}
                  className={`cursor-pointer border-t border-slate-800 hover:bg-slate-900 ${
                    selected?.id === c.id ? "bg-slate-800" : ""
                  }`}
                >
                  <td className="px-2 py-1 font-mono text-slate-300">
                    {new Date(c.started_at).toLocaleString()}
                  </td>
                  <td className="px-2">{c.camera_id}</td>
                  <td className="px-2 text-slate-400">{c.pipeline_id ?? "—"}</td>
                  <td className="px-2 text-slate-400">{fmtBytes(c.size_bytes)}</td>
                  <td className="px-2 text-right">
                    {!c.exists && <span className="text-rose-400">missing</span>}
                    <button
                      onClick={(e) => { e.stopPropagation(); remove(c); }}
                      className="ml-2 text-rose-400 hover:underline"
                    >
                      delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          )}
        </div>
      </div>

      <div className="flex w-1/2 min-w-0 flex-col">
        {selected ? (
          <>
            <div className="flex shrink-0 items-center justify-between border-b border-slate-800 bg-slate-900 px-3 py-2 text-xs">
              <span className="font-mono text-slate-300">{selected.id}</span>
              <a
                href={api.clipFileUrl(selected.id)}
                download
                className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800"
              >Download</a>
            </div>
            <div className="min-h-0 flex-1 bg-black">
              {selected.is_image ? (
                <img
                  key={selected.id}
                  src={api.clipFileUrl(selected.id)}
                  alt=""
                  className="h-full w-full object-contain"
                />
              ) : (
                <video
                  key={selected.id}
                  controls
                  autoPlay
                  src={api.clipFileUrl(selected.id)}
                  className="h-full w-full object-contain"
                />
              )}
            </div>
            <div className="shrink-0 border-t border-slate-800 bg-slate-950 p-2 text-xs text-slate-400">
              <div>started: {selected.started_at}</div>
              <div>ended: {selected.ended_at ?? "—"}</div>
              {selected.trigger != null && (
                <pre className="mt-1 whitespace-pre-wrap text-slate-500">
                  trigger: {JSON.stringify(selected.trigger, null, 2)}
                </pre>
              )}
            </div>
          </>
        ) : (
          <div className="m-auto text-sm text-slate-500">Select a clip to play.</div>
        )}
      </div>
    </div>
  );
}
