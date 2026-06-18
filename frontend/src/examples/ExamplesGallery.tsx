import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, CameraInfo } from "../api/client";

type Example = Awaited<ReturnType<typeof api.listExamples>>[number];

const COMPLEXITY_COLOR: Record<string, string> = {
  simple: "bg-emerald-700 text-emerald-100",
  medium: "bg-amber-700 text-amber-100",
  advanced: "bg-rose-700 text-rose-100",
};

export default function ExamplesGallery() {
  const [examples, setExamples] = useState<Example[]>([]);
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [filter, setFilter] = useState("");
  const [installing, setInstalling] = useState<Example | null>(null);

  useEffect(() => {
    api.listExamples().then(setExamples).catch(console.warn);
    api.listCameras().then(setCameras).catch(console.warn);
  }, []);

  const visible = examples.filter((e) => {
    if (!filter) return true;
    const f = filter.toLowerCase();
    return e.name.toLowerCase().includes(f)
      || e.description.toLowerCase().includes(f)
      || e.tags.some((t) => t.toLowerCase().includes(f))
      || e.id.toLowerCase().includes(f);
  });

  return (
    <div className="h-full overflow-auto bg-slate-950">
      <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-slate-800 bg-slate-900/90 px-4 py-3 backdrop-blur">
        <h2 className="text-lg font-semibold">Pipeline examples</h2>
        <span className="text-xs text-slate-500">{visible.length} of {examples.length}</span>
        <input
          placeholder="filter (tag, name, description)…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="ml-auto w-64 rounded bg-slate-950 px-2 py-1 text-sm"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2 lg:grid-cols-3">
        {visible.map((e) => (
          <div
            key={e.id}
            className="flex flex-col rounded-lg border border-slate-800 bg-slate-900 p-3"
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="font-mono text-xs text-slate-400">{e.id}</span>
              <span className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${COMPLEXITY_COLOR[e.complexity] ?? "bg-slate-700"}`}>
                {e.complexity}
              </span>
            </div>
            <h3 className="mb-1 text-sm font-semibold">{e.name}</h3>
            <p className="mb-2 text-xs text-slate-400">{e.description}</p>
            {e.use_case && (
              <p className="mb-2 text-[11px] italic text-slate-500">{e.use_case}</p>
            )}
            <div className="mb-2 flex flex-wrap gap-1">
              {e.tags.map((t) => (
                <span key={t} className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                  {t}
                </span>
              ))}
            </div>
            <div className="mb-2 text-[11px] text-slate-500">
              <span className="text-slate-400">Nodes</span>: {e.definition.nodes.length} ·
              <span className="ml-1 text-slate-400">Edges</span>: {e.definition.edges.length}
              {e.requires_env.length > 0 && (
                <div className="mt-1 text-amber-400">
                  requires env: {e.requires_env.join(", ")}
                </div>
              )}
            </div>
            <button
              onClick={() => setInstalling(e)}
              className="mt-auto rounded bg-blue-600 px-3 py-1.5 text-sm font-medium hover:bg-blue-500"
            >
              Install →
            </button>
          </div>
        ))}
      </div>

      {installing && (
        <InstallDialog
          example={installing}
          cameras={cameras}
          onClose={() => setInstalling(null)}
        />
      )}
    </div>
  );
}

function InstallDialog({
  example, cameras, onClose,
}: {
  example: Example; cameras: CameraInfo[]; onClose: () => void;
}) {
  const navigate = useNavigate();
  const [mapping, setMapping] = useState<Record<string, string>>(() => {
    const m: Record<string, string> = {};
    for (const p of example.placeholders) m[p] = "";
    return m;
  });
  const [targetId, setTargetId] = useState(example.id);
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function install() {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.installExample(example.id, {
        camera_map: mapping, target_id: targetId, enabled,
      });
      navigate(`/editor/${r.id}`);
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           className="w-[480px] max-w-[90vw] rounded-lg border border-slate-700 bg-slate-900 shadow-xl">
        <div className="border-b border-slate-800 px-4 py-3">
          <div className="text-sm font-semibold">Install: {example.name}</div>
          <div className="text-xs text-slate-500">{example.id}</div>
        </div>
        <div className="space-y-3 p-4 text-sm">
          <div className="text-slate-300">{example.description}</div>
          {example.use_case && (
            <div className="rounded border border-slate-800 bg-slate-950 p-2 text-xs italic text-slate-400">
              {example.use_case}
            </div>
          )}

          <label className="flex items-center gap-3">
            <span className="w-32 text-slate-400">Pipeline id</span>
            <input
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              className="flex-1 rounded bg-slate-950 px-2 py-1"
            />
          </label>

          {example.placeholders.length > 0 && (
            <div className="space-y-2 rounded border border-slate-800 p-2">
              <div className="text-xs font-semibold text-slate-300">Map placeholder cameras:</div>
              {example.placeholders.map((p) => (
                <label key={p} className="flex items-center gap-3 text-xs">
                  <span className="w-32 truncate font-mono text-slate-500">{p}</span>
                  <select
                    value={mapping[p] || ""}
                    onChange={(e) => setMapping({ ...mapping, [p]: e.target.value })}
                    className="flex-1 rounded bg-slate-950 px-2 py-1"
                  >
                    <option value="">— pick a camera —</option>
                    {cameras.map((c) => (
                      <option key={c.id} value={c.id}>{c.id} · {c.label || c.kind}</option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          )}

          {example.requires_env.length > 0 && (
            <div className="rounded border border-amber-800 bg-amber-950/40 p-2 text-xs text-amber-300">
              Requires env vars: <code>{example.requires_env.join(", ")}</code>
              <div className="mt-1 text-amber-200/80">
                Set them in the shell running the backend, then restart.
              </div>
            </div>
          )}

          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Start immediately
          </label>

          {err && <div className="rounded bg-red-950 p-2 text-xs text-red-300">{err}</div>}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-800 bg-slate-950 px-4 py-3">
          <button
            onClick={onClose}
            className="rounded border border-slate-700 px-3 py-1 text-sm hover:bg-slate-800"
          >Cancel</button>
          <button
            onClick={install}
            disabled={busy}
            className="rounded bg-blue-600 px-3 py-1 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
          >
            {busy ? "Installing…" : "Install + Open in editor"}
          </button>
        </div>
      </div>
    </div>
  );
}
