import { useEffect, useMemo, useRef, useState } from "react";

type Event = { kind: string; ts: number; pipeline_id: string; camera_id: string | null; payload?: unknown };

const COLORS: Record<string, string> = {
  zone_enter: "#22d3ee", zone_leave: "#0891b2", zone_dwell: "#0e7490",
  temperature_gate: "#f97316",
  metadata_match: "#a855f7", counter: "#c084fc",
  line_crossing: "#fb7185",
  console: "#94a3b8",
  vision_description: "#34d399",
  default: "#64748b",
};

export default function TimelineTile({ onRemove }: { onRemove?: () => void }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [windowMins, setWindowMins] = useState(15);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const es = new EventSource("/api/events/stream");
    es.addEventListener("event", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      const ev: Event = {
        kind: d.kind, ts: Date.now(),
        pipeline_id: d.pipeline_id, camera_id: d.camera_id, payload: d.payload,
      };
      setEvents((prev) => [...prev, ev].slice(-2000));
    });
    return () => es.close();
  }, []);

  // Group into rows by pipeline_id
  const rows = useMemo(() => {
    const cutoff = Date.now() - windowMins * 60_000;
    const byPipe = new Map<string, Event[]>();
    for (const e of events) {
      if (e.ts < cutoff) continue;
      const arr = byPipe.get(e.pipeline_id) || [];
      arr.push(e);
      byPipe.set(e.pipeline_id, arr);
    }
    return Array.from(byPipe.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [events, windowMins]);

  const tNow = Date.now();
  const tStart = tNow - windowMins * 60_000;

  return (
    <div className="flex h-full w-full flex-col">
      <div className="drag-handle flex h-7 shrink-0 cursor-move items-center justify-between border-b border-slate-800 bg-slate-950 px-3 text-xs select-none">
        <span className="flex items-center gap-2">
          <span className="rounded bg-cyan-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-cyan-100">
            timeline
          </span>
          <span>last {windowMins}m</span>
        </span>
        <span className="ml-2 flex shrink-0 items-center gap-1 text-slate-500">
          <select
            onMouseDown={(e) => e.stopPropagation()}
            onChange={(e) => setWindowMins(Number(e.target.value))}
            value={windowMins}
            className="rounded bg-slate-900 px-1 py-0.5"
          >
            <option value={5}>5 min</option>
            <option value={15}>15 min</option>
            <option value={60}>1 hour</option>
            <option value={360}>6 hours</option>
          </select>
          {onRemove && (
            <button
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); if (confirm("Remove timeline tile?")) onRemove(); }}
              className="rounded border border-red-700 px-1 text-[10px] text-red-300 hover:bg-red-900"
            >×</button>
          )}
        </span>
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto bg-slate-950 p-2 text-xs">
        {rows.length === 0 && <div className="text-slate-600">(no events in window — waiting…)</div>}
        {rows.map(([pid, evs]) => (
          <div key={pid} className="mb-3">
            <div className="mb-1 truncate font-mono text-[10px] text-slate-400">{pid} · {evs.length}</div>
            <div className="relative h-6 rounded bg-slate-900">
              {evs.map((e, i) => {
                const x = ((e.ts - tStart) / (tNow - tStart)) * 100;
                return (
                  <div
                    key={i}
                    title={`${e.kind} · ${new Date(e.ts).toLocaleTimeString()} · ${e.camera_id ?? ""}`}
                    style={{
                      left: `${Math.max(0, Math.min(100, x))}%`,
                      background: COLORS[e.kind] || COLORS.default,
                    }}
                    className="absolute top-1 h-4 w-1 rounded-sm hover:w-2"
                  />
                );
              })}
            </div>
          </div>
        ))}
        <div className="mt-2 flex justify-between text-[10px] text-slate-500">
          <span>{new Date(tStart).toLocaleTimeString()}</span>
          <span>now</span>
        </div>
      </div>
    </div>
  );
}
