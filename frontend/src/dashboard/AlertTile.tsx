import { useEffect, useRef, useState } from "react";

export type AlertConfig = {
  label: string;
  pipelineFilter?: string;
  kindFilter?: string;     // e.g. "zone_enter,temperature_gate"
  sound: boolean;
  flashMs: number;
};

type AlertEntry = {
  ts: string;
  kind: string;
  pipeline_id: string;
  camera_id: string | null;
  payload: Record<string, unknown>;
};

export default function AlertTile({
  config,
  onConfigChange,
  onRemove,
}: {
  config: AlertConfig;
  onConfigChange: (cfg: AlertConfig) => void;
  onRemove: () => void;
}) {
  const [entries, setEntries] = useState<AlertEntry[]>([]);
  const [flashing, setFlashing] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const wantedKinds = (config.kindFilter ?? "")
      .split(",").map((s) => s.trim()).filter(Boolean);
    const es = new EventSource("/api/events/stream");
    es.addEventListener("event", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      if (config.pipelineFilter && data.pipeline_id !== config.pipelineFilter) return;
      if (wantedKinds.length > 0 && !wantedKinds.includes(data.kind)) return;
      const entry: AlertEntry = {
        ts: new Date().toLocaleTimeString(),
        kind: data.kind,
        pipeline_id: data.pipeline_id,
        camera_id: data.camera_id,
        payload: data.payload,
      };
      setEntries((prev) => [entry, ...prev].slice(0, 50));
      setFlashing(true);
      setTimeout(() => setFlashing(false), config.flashMs);
      if (config.sound && audioRef.current) {
        audioRef.current.currentTime = 0;
        audioRef.current.play().catch(() => {});
      }
    });
    return () => es.close();
  }, [config.pipelineFilter, config.kindFilter, config.sound, config.flashMs]);

  return (
    <div className="flex h-full w-full flex-col">
      <div className={`drag-handle flex h-7 shrink-0 cursor-move items-center justify-between border-b px-3 text-xs select-none transition-colors ${
        flashing ? "border-red-500 bg-red-900 animate-pulse" : "border-slate-800 bg-slate-950"
      }`}>
        <span className="flex items-center gap-2">
          <span className="rounded bg-rose-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-rose-100">
            alert
          </span>
          <span>{config.label || "alerts"}</span>
        </span>
        <span className="ml-2 flex shrink-0 items-center gap-2 text-slate-500">
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
            onClick={(e) => { e.stopPropagation(); if (confirm("Remove alert tile?")) onRemove(); }}
            className="rounded border border-red-700 px-1 text-[10px] text-red-300 hover:bg-red-900"
          >×</button>
        </span>
      </div>

      {showConfig && (
        <div className="flex shrink-0 flex-col gap-1 border-b border-slate-800 bg-slate-950 p-2 text-xs">
          <ConfigRow label="Label">
            <input className="flex-1 rounded bg-slate-900 px-2 py-0.5"
                   value={config.label}
                   onMouseDown={(e) => e.stopPropagation()}
                   onChange={(e) => onConfigChange({ ...config, label: e.target.value })} />
          </ConfigRow>
          <ConfigRow label="Pipeline">
            <input className="flex-1 rounded bg-slate-900 px-2 py-0.5" placeholder="(all)"
                   value={config.pipelineFilter ?? ""}
                   onMouseDown={(e) => e.stopPropagation()}
                   onChange={(e) => onConfigChange({ ...config, pipelineFilter: e.target.value || undefined })} />
          </ConfigRow>
          <ConfigRow label="Kinds">
            <input className="flex-1 rounded bg-slate-900 px-2 py-0.5"
                   placeholder="comma-sep, e.g. zone_enter,temperature_gate"
                   value={config.kindFilter ?? ""}
                   onMouseDown={(e) => e.stopPropagation()}
                   onChange={(e) => onConfigChange({ ...config, kindFilter: e.target.value || undefined })} />
          </ConfigRow>
          <ConfigRow label="Sound">
            <input type="checkbox" checked={config.sound}
                   onMouseDown={(e) => e.stopPropagation()}
                   onChange={(e) => onConfigChange({ ...config, sound: e.target.checked })} />
          </ConfigRow>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto bg-black p-2 font-mono text-[11px] text-slate-200">
        {entries.length === 0 && (
          <div className="text-slate-600">
            (no alerts yet · filters: {config.pipelineFilter || "all pipelines"} / {config.kindFilter || "all kinds"})
          </div>
        )}
        {entries.map((e, i) => (
          <div key={i} className={`my-1 rounded border-l-2 border-rose-500 bg-rose-950/40 px-2 py-1 ${i === 0 ? "ring-1 ring-rose-500" : ""}`}>
            <div className="flex gap-2 text-rose-300">
              <span>{e.ts}</span>
              <span className="font-bold">{e.kind}</span>
              <span className="text-slate-400">{e.pipeline_id}</span>
              {e.camera_id && <span className="text-slate-400">· {e.camera_id}</span>}
            </div>
            <pre className="whitespace-pre-wrap break-words pl-2 text-slate-300">
              {JSON.stringify(e.payload, null, 0)}
            </pre>
          </div>
        ))}
      </div>

      {/* Short data-uri beep (~500Hz, 200ms). Browser will block autoplay until user gesture. */}
      <audio ref={audioRef} preload="auto"
             src="data:audio/wav;base64,UklGRtwAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YbgAAAAAAAQAcgD3AKwAFwGiAOEAUACEAJAAhgB9AHEAOgDz/4n/Iv+m/iv+lP0K/Wn82vtN++r6XfoH+sH5lvmJ+Wj5l/m4+QH6Tvqz+i77t/tT/AD9k/0w/sn+Pv+x/wkAUgB6AKgAuQDXAOAA+wACAR0BEgEcAQUB+wDcAMgArACVAH8AeQB7AIoAlgC7ANgADAEzAWQBfgGfAaMBuAGqAakBhAFmATQB" />
    </div>
  );
}

function ConfigRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-2">
      <span className="w-16 text-slate-400">{label}</span>
      {children}
    </label>
  );
}
