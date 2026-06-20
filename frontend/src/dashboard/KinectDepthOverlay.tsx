import { RefObject, useEffect, useRef, useState } from "react";
import { depthSubscribe } from "../api/client";

type Unit = "mm" | "cm" | "m" | "ft";

const UNIT_STORAGE_KEY = "camera_dash.depth.unit";

function formatDistance(mm: number, unit: Unit): string {
  if (!isFinite(mm) || mm <= 0) return "—";
  switch (unit) {
    case "mm": return `${Math.round(mm)} mm`;
    case "cm": return `${(mm / 10).toFixed(1)} cm`;
    case "m":  return `${(mm / 1000).toFixed(2)} m`;
    case "ft": return `${(mm / 304.8).toFixed(2)} ft`;
  }
}

/**
 * Depth-on-hover overlay for Kinect (or any DepthFrame-producing camera).
 *
 * Subscribes to /api/depth/{camera} and keeps the latest mm matrix in a ref.
 * On mouse hover, looks up the pixel and renders it. The matrix is downsampled
 * to ~320 wide on the server; we scale cursor coords to that resolution.
 */
export default function KinectDepthOverlay({
  cameraId,
  videoRef: _videoRef,
}: {
  cameraId: string;
  videoRef: RefObject<HTMLVideoElement>;
}) {
  const matrixRef = useRef<{ w: number; h: number; data: Uint16Array } | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; mm: number } | null>(null);
  const [unit, setUnit] = useState<Unit>(() => {
    const v = localStorage.getItem(UNIT_STORAGE_KEY);
    return v === "mm" || v === "cm" || v === "m" || v === "ft" ? v : "m";
  });
  const [stats, setStats] = useState<{ min: number; max: number; valid_pct: number } | null>(null);

  useEffect(() => {
    localStorage.setItem(UNIT_STORAGE_KEY, unit);
  }, [unit]);

  useEffect(() => {
    return depthSubscribe(cameraId, (w, h, data) => {
      matrixRef.current = { w, h, data };
      // Compute min/max over valid pixels for the toolbar readout. Cheap
      // enough at 320x240 to do every frame.
      let lo = Infinity;
      let hi = -Infinity;
      let valid = 0;
      for (let i = 0; i < data.length; i++) {
        const v = data[i];
        if (v === 0) continue;
        valid++;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      setStats(valid === 0
        ? { min: 0, max: 0, valid_pct: 0 }
        : { min: lo, max: hi, valid_pct: (100 * valid) / data.length });
    });
  }, [cameraId]);

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const m = matrixRef.current;
    if (!m) return;
    const r = e.currentTarget.getBoundingClientRect();
    const xn = (e.clientX - r.left) / r.width;
    const yn = (e.clientY - r.top) / r.height;
    if (xn < 0 || xn > 1 || yn < 0 || yn > 1) return;
    const xi = Math.min(m.w - 1, Math.max(0, Math.floor(xn * m.w)));
    const yi = Math.min(m.h - 1, Math.max(0, Math.floor(yn * m.h)));
    const mm = m.data[yi * m.w + xi];
    setHover({ x: e.clientX - r.left, y: e.clientY - r.top, mm });
  }

  return (
    <div
      className="pointer-events-auto absolute inset-0"
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
    >
      {/* Cursor readout */}
      {hover && (
        <div
          className="pointer-events-none absolute rounded bg-slate-900/90 px-2 py-1 text-xs text-white shadow"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
        >
          {formatDistance(hover.mm, unit)}
          {hover.mm === 0 && <span className="ml-1 text-slate-400">(no reading)</span>}
        </div>
      )}

      {/* Toolbar — unit selector + scene stats. Anchored bottom-right so it
          doesn't fight the FLIR overlay on shared layouts. */}
      <div className="pointer-events-auto absolute bottom-1 right-1 flex items-center gap-2 rounded bg-slate-900/80 px-2 py-1 text-[10px] text-slate-200">
        <span className="text-slate-400">depth</span>
        <select
          className="rounded bg-slate-800 px-1 text-[10px]"
          value={unit}
          onChange={(e) => setUnit(e.target.value as Unit)}
        >
          <option value="m">m</option>
          <option value="cm">cm</option>
          <option value="mm">mm</option>
          <option value="ft">ft</option>
        </select>
        {stats && stats.valid_pct > 0 ? (
          <span className="text-slate-400">
            range {formatDistance(stats.min, unit)}–{formatDistance(stats.max, unit)} ·{" "}
            {stats.valid_pct.toFixed(0)}% valid
          </span>
        ) : (
          <span className="italic text-slate-500">waiting for depth…</span>
        )}
      </div>
    </div>
  );
}
