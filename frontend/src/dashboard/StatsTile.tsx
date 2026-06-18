import { useEffect, useState } from "react";
import { api } from "../api/client";

type Stats = Awaited<ReturnType<typeof api.stats>>;

export default function StatsTile({ onRemove }: { onRemove?: () => void }) {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const s = await api.stats();
        if (!cancelled) setStats(s);
      } catch { /* ignore */ }
    }
    refresh();
    const t = setInterval(refresh, 1000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  return (
    <div className="flex h-full w-full flex-col">
      <div className="drag-handle flex h-7 shrink-0 cursor-move items-center justify-between border-b border-slate-800 bg-slate-950 px-3 text-xs select-none">
        <span className="flex items-center gap-2">
          <span className="rounded bg-emerald-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-emerald-100">
            stats
          </span>
          <span>performance</span>
        </span>
        {onRemove && (
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); if (confirm("Remove stats tile?")) onRemove(); }}
            className="rounded border border-red-700 px-1 text-[10px] text-red-300 hover:bg-red-900"
          >×</button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto bg-slate-950 p-2 text-xs">
        {!stats && <div className="text-slate-500">loading…</div>}
        {stats && (
          <>
            <Section title={`Cameras (${stats.cameras.length})`}>
              {stats.cameras.map((c) => (
                <Row key={c.id} label={`${c.label} · ${c.kind}`}
                     fps={c.fps} subs={c.subscribers} running={c.running} />
              ))}
            </Section>
            {stats.derived.length > 0 && (
              <Section title={`Derived streams (${stats.derived.length})`}>
                {stats.derived.map((s) => (
                  <Row key={s.id} label={s.label} fps={s.fps} subs={s.subscribers} running />
                ))}
              </Section>
            )}
            <Section title={`Pipelines (${Object.keys(stats.pipelines).length})`}>
              {Object.entries(stats.pipelines).map(([pid, p]) => (
                <div key={pid} className="flex justify-between border-b border-slate-900 py-0.5">
                  <span className="truncate font-mono">{pid}</span>
                  <span className="text-slate-400">
                    {p.running}/{p.nodes.length} nodes
                  </span>
                </div>
              ))}
            </Section>
          </>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">{title}</div>
      {children}
    </div>
  );
}

function Row({ label, fps, subs, running }:
  { label: string; fps: number; subs: number; running: boolean }) {
  return (
    <div className="flex items-baseline justify-between border-b border-slate-900 py-0.5">
      <span className={`truncate ${running ? "" : "text-slate-600"}`}>
        {running ? "" : "○ "}{label}
      </span>
      <span className="ml-2 shrink-0 font-mono text-slate-400">
        {fps.toFixed(1)} fps · {subs} sub
      </span>
    </div>
  );
}
