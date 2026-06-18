import { useEffect, useRef, useState } from "react";

export type LogConfig = {
  label: string;
  pipelineFilter?: string;  // empty / undefined = all pipelines
  kindFilter?: string;      // empty / undefined = all kinds
};

type Entry = {
  ts: string;
  pipeline_id: string;
  node_id?: string;
  camera_id: string | null;
  kind: string;
  payload: Record<string, unknown>;
};

export default function LogTile({
  config,
  onConfigChange,
  onRemove,
}: {
  config: LogConfig;
  onConfigChange: (cfg: LogConfig) => void;
  onRemove: () => void;
}) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [paused, setPaused] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickyBottomRef = useRef(true);

  useEffect(() => {
    if (paused) return;
    const es = new EventSource("/api/events/stream");
    es.addEventListener("event", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      if (config.pipelineFilter && data.pipeline_id !== config.pipelineFilter) return;
      if (config.kindFilter && data.kind !== config.kindFilter) return;
      const entry: Entry = {
        ts: new Date().toLocaleTimeString(),
        pipeline_id: data.pipeline_id,
        node_id: data.node_id,
        camera_id: data.camera_id,
        kind: data.kind,
        payload: data.payload,
      };
      setEntries((prev) => [...prev, entry].slice(-500));
    });
    return () => es.close();
  }, [paused, config.pipelineFilter, config.kindFilter]);

  // Auto-scroll to bottom unless user scrolled up
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !stickyBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [entries]);

  function onScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    stickyBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  }

  return (
    <div className="flex h-full w-full flex-col">
      <div className="drag-handle flex h-7 shrink-0 cursor-move items-center justify-between border-b border-slate-800 bg-slate-950 px-3 text-xs select-none">
        <span className="flex min-w-0 items-center gap-2 truncate">
          <span className="rounded bg-amber-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-amber-100">
            log
          </span>
          <span className="truncate">{config.label || "events"}</span>
          {config.pipelineFilter && (
            <span className="rounded bg-slate-800 px-1 text-[10px] text-slate-400">
              p:{config.pipelineFilter}
            </span>
          )}
          {config.kindFilter && (
            <span className="rounded bg-slate-800 px-1 text-[10px] text-slate-400">
              k:{config.kindFilter}
            </span>
          )}
        </span>
        <span className="ml-2 flex shrink-0 items-center gap-2 text-slate-500">
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); setPaused((p) => !p); }}
            className="rounded border border-slate-700 px-1 text-[10px] hover:bg-slate-800"
          >{paused ? "▶" : "❚❚"}</button>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); setEntries([]); }}
            className="rounded border border-slate-700 px-1 text-[10px] hover:bg-slate-800"
          >clear</button>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); setShowConfig((s) => !s); }}
            className="rounded border border-slate-700 px-1 text-[10px] hover:bg-slate-800"
          >⚙</button>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); if (confirm("Remove this log tile?")) onRemove(); }}
            className="rounded border border-red-700 px-1 text-[10px] text-red-300 hover:bg-red-900"
          >×</button>
        </span>
      </div>

      {showConfig && (
        <div className="flex shrink-0 flex-col gap-1 border-b border-slate-800 bg-slate-950 p-2 text-xs">
          <label className="flex items-center gap-2">
            <span className="w-16 text-slate-400">Label</span>
            <input
              className="flex-1 rounded bg-slate-900 px-2 py-0.5"
              value={config.label}
              onMouseDown={(e) => e.stopPropagation()}
              onChange={(e) => onConfigChange({ ...config, label: e.target.value })}
            />
          </label>
          <label className="flex items-center gap-2">
            <span className="w-16 text-slate-400">Pipeline</span>
            <input
              className="flex-1 rounded bg-slate-900 px-2 py-0.5"
              placeholder="(all)"
              value={config.pipelineFilter ?? ""}
              onMouseDown={(e) => e.stopPropagation()}
              onChange={(e) => onConfigChange({ ...config, pipelineFilter: e.target.value || undefined })}
            />
          </label>
          <label className="flex items-center gap-2">
            <span className="w-16 text-slate-400">Kind</span>
            <input
              className="flex-1 rounded bg-slate-900 px-2 py-0.5"
              placeholder="(all)"
              value={config.kindFilter ?? ""}
              onMouseDown={(e) => e.stopPropagation()}
              onChange={(e) => onConfigChange({ ...config, kindFilter: e.target.value || undefined })}
            />
          </label>
        </div>
      )}

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-auto bg-black p-2 font-mono text-[11px] text-slate-200"
      >
        {entries.length === 0 && (
          <div className="text-slate-600">(waiting for events…)</div>
        )}
        {entries.map((e, i) => (
          <div key={i} className="border-b border-slate-900 py-0.5">
            <div className="flex gap-2 text-slate-500">
              <span>{e.ts}</span>
              <span className="text-amber-400">{e.kind}</span>
              <span className="text-slate-400">{e.pipeline_id}</span>
              {e.camera_id && <span className="text-slate-400">· {e.camera_id}</span>}
            </div>
            <pre className="whitespace-pre-wrap break-words pl-2 text-slate-300">
              {(e.payload as { formatted?: string }).formatted ??
                JSON.stringify(e.payload, null, 2)}
            </pre>
          </div>
        ))}
      </div>
    </div>
  );
}
