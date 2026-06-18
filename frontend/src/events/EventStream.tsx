import { useEffect, useState } from "react";
import { api } from "../api/client";

type EvtRow = {
  pipeline_id: string;
  node_id?: string;
  camera_id: string | null;
  kind: string;
  payload: unknown;
  timestamp?: string;
};

export default function EventStream() {
  const [live, setLive] = useState<EvtRow[]>([]);
  const [paused, setPaused] = useState(false);
  const [history, setHistory] = useState<EvtRow[]>([]);

  useEffect(() => {
    if (paused) return;
    const es = api.eventStream((e) => {
      setLive((prev) => [{ ...e, timestamp: new Date().toISOString() }, ...prev].slice(0, 200));
    });
    return () => es.close();
  }, [paused]);

  useEffect(() => {
    api.listEvents({ limit: 50 }).then((rows) => setHistory(rows as EvtRow[]));
  }, []);

  return (
    <div className="h-full overflow-auto p-4">
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-xl font-semibold">Events</h2>
        <button
          className="rounded border border-slate-700 px-3 py-1 text-sm hover:bg-slate-800"
          onClick={() => setPaused((p) => !p)}
        >
          {paused ? "Resume" : "Pause"}
        </button>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Pane title={`Live${paused ? " (paused)" : ""}`} rows={live} />
        <Pane title="Recent (DB)" rows={history} />
      </div>
    </div>
  );
}

function Pane({ title, rows }: { title: string; rows: EvtRow[] }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 px-3 py-2 text-sm font-semibold">{title}</div>
      <div className="max-h-[80vh] overflow-auto p-2 text-xs">
        {rows.length === 0 && <div className="p-4 text-slate-500">(no events)</div>}
        {rows.map((e, i) => (
          <div key={i} className="border-b border-slate-800 py-1">
            <div className="flex items-center justify-between text-slate-400">
              <span className="font-mono">{e.kind}</span>
              <span>{e.timestamp ?? ""}</span>
            </div>
            <div className="text-slate-300">
              {e.pipeline_id} · {e.camera_id ?? "—"}
            </div>
            <pre className="mt-1 whitespace-pre-wrap font-mono text-slate-400">{JSON.stringify(e.payload, null, 2)}</pre>
          </div>
        ))}
      </div>
    </div>
  );
}
