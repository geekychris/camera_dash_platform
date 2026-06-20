import { useEffect, useState } from "react";
import { SnapshotInfo } from "../api/client";

/**
 * Dashboard tile for a ``broadcast.snapshot`` node. The backend keeps the
 * latest JPEG in a registry and serves it at
 * /api/broadcast/snapshot/<id>.jpg; we just `<img>` it and refresh on a
 * timer. Cache-busting query string forces a real GET each tick — the
 * server's response Content-Type is JPEG so the browser doesn't try to
 * cache anyway, but the timestamp keeps URL-level cache layers honest.
 */
export default function SnapshotTile({ info }: { info: SnapshotInfo }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    // The node itself caps at `target_fps` (default 2 Hz). Polling faster
    // than that on the client just hits the same JPEG bytes — match the
    // server's typical cadence so we don't burn CPU on no-op renders.
    const id = setInterval(() => setTick((t) => t + 1), 500);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex h-full w-full flex-col">
      <div className="drag-handle flex h-7 shrink-0 cursor-move items-center justify-between border-b border-slate-800 bg-slate-950 px-3 text-xs select-none">
        <span className="flex min-w-0 items-center gap-2 truncate">
          <span className="rounded bg-sky-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-sky-100">
            snapshot
          </span>
          <span className="truncate">{info.label || info.id}</span>
        </span>
        <span className="ml-2 flex shrink-0 items-center gap-1 text-slate-500">
          <span>{info.width}×{info.height}</span>
        </span>
      </div>
      <div className="relative min-h-0 flex-1 overflow-hidden bg-black">
        <img
          src={`${info.url}?t=${tick}`}
          alt={info.id}
          className="absolute inset-0 m-auto max-h-full max-w-full"
        />
      </div>
    </div>
  );
}
