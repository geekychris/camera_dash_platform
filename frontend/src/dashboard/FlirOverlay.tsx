import { RefObject, useEffect, useRef, useState } from "react";
import { radiometricSubscribe } from "../api/client";

type Pin = { x: number; y: number; celsius: number; raw: number; ts: number };
type Stats = { min: number; max: number; center: number; rawMin: number; rawMax: number };

const PIN_STORAGE_PREFIX = "camera_dash.flir.pins.";

function ck2c(centiK: number): number {
  return centiK / 100 - 273.15;
}

/**
 * Heuristic: if the matrix's centi-Kelvin range is outside the plausible thermal
 * scene range (~ -40°C to 200°C ≈ centi-K 23000..47000), assume the camera is
 * in AGC mode (auto-stretched 14-bit counts, not real radiometric).
 */
function looksRadiometric(stats: Stats): boolean {
  return stats.rawMin > 22000 && stats.rawMax < 47500;
}

export default function FlirOverlay({
  cameraId,
  // videoRef intentionally accepted but unused — keeps the existing call site stable
  videoRef: _videoRef,
}: {
  cameraId: string;
  videoRef: RefObject<HTMLVideoElement>;
}) {
  const matrixRef = useRef<{ w: number; h: number; data: Uint16Array } | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; celsius: number; raw: number } | null>(null);
  const [pins, setPins] = useState<Pin[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(PIN_STORAGE_PREFIX + cameraId) || "[]");
    } catch { return []; }
  });
  const [stats, setStats] = useState<Stats | null>(null);

  // Subscribe to radiometric WS + maintain rolling stats
  useEffect(() => {
    return radiometricSubscribe(cameraId, (w, h, data) => {
      matrixRef.current = { w, h, data };
      // Frame stats — only recompute every ~250ms to avoid React thrashing
      const now = performance.now();
      if (!(window as any).__flirStatsLast || now - (window as any).__flirStatsLast > 250) {
        (window as any).__flirStatsLast = now;
        let mn = data[0], mx = data[0];
        for (let i = 1; i < data.length; i++) {
          const v = data[i];
          if (v < mn) mn = v;
          else if (v > mx) mx = v;
        }
        const cx = Math.floor(w / 2), cy = Math.floor(h / 2);
        const center = data[cy * w + cx];
        setStats({
          rawMin: mn, rawMax: mx,
          min: ck2c(mn), max: ck2c(mx), center: ck2c(center),
        });
      }
    });
  }, [cameraId]);

  // Refresh pinned points' temperatures as new frames arrive
  useEffect(() => {
    if (pins.length === 0) return;
    const t = setInterval(() => {
      const m = matrixRef.current;
      if (!m) return;
      setPins((prev) => prev.map((p) => {
        const mx = Math.min(m.w - 1, Math.max(0, Math.floor(p.x * m.w)));
        const my = Math.min(m.h - 1, Math.max(0, Math.floor(p.y * m.h)));
        const raw = m.data[my * m.w + mx];
        return { ...p, raw, celsius: ck2c(raw) };
      }));
    }, 500);
    return () => clearInterval(t);
  }, [pins.length]);

  function eventToFrac(e: React.MouseEvent<HTMLDivElement>): { px: number; py: number; cx: number; cy: number } {
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width;
    const py = (e.clientY - rect.top) / rect.height;
    return { px, py, cx: e.clientX - rect.left, cy: e.clientY - rect.top };
  }

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const m = matrixRef.current;
    if (!m) return;
    const { px, py, cx, cy } = eventToFrac(e);
    const mx = Math.min(m.w - 1, Math.max(0, Math.floor(px * m.w)));
    const my = Math.min(m.h - 1, Math.max(0, Math.floor(py * m.h)));
    const raw = m.data[my * m.w + mx];
    setHover({ x: cx, y: cy, celsius: ck2c(raw), raw });
  }

  function onClick(e: React.MouseEvent<HTMLDivElement>) {
    e.stopPropagation();
    const m = matrixRef.current;
    if (!m) return;
    const { px, py } = eventToFrac(e);
    const mx = Math.min(m.w - 1, Math.max(0, Math.floor(px * m.w)));
    const my = Math.min(m.h - 1, Math.max(0, Math.floor(py * m.h)));
    const raw = m.data[my * m.w + mx];
    const next: Pin[] = [...pins, { x: px, y: py, celsius: ck2c(raw), raw, ts: Date.now() }];
    setPins(next);
    localStorage.setItem(PIN_STORAGE_PREFIX + cameraId, JSON.stringify(next));
  }

  function removePin(i: number, e: React.MouseEvent) {
    e.stopPropagation();
    const next = pins.filter((_, j) => j !== i);
    setPins(next);
    localStorage.setItem(PIN_STORAGE_PREFIX + cameraId, JSON.stringify(next));
  }

  function clearPins(e: React.MouseEvent) {
    e.stopPropagation();
    setPins([]);
    localStorage.removeItem(PIN_STORAGE_PREFIX + cameraId);
  }

  const isCalibrated = stats ? looksRadiometric(stats) : true;

  return (
    <div
      className="pointer-events-auto absolute inset-0 cursor-crosshair"
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
      onClick={onClick}
    >
      {/* Always-visible frame stats (top-left) */}
      {stats && (
        <div className="pointer-events-none absolute left-1 top-1 rounded bg-black/70 px-2 py-1 text-[10px] font-mono text-white shadow">
          {isCalibrated ? (
            <>
              <div>min {stats.min.toFixed(1)}°C · max {stats.max.toFixed(1)}°C</div>
              <div>center {stats.center.toFixed(1)}°C</div>
            </>
          ) : (
            <>
              <div className="text-amber-300">⚠ AGC mode — raw counts (no °C)</div>
              <div className="text-slate-300">range {stats.rawMin}..{stats.rawMax}</div>
            </>
          )}
        </div>
      )}

      {/* AGC warning banner */}
      {stats && !isCalibrated && (
        <a
          href="https://github.com/groupgets/purethermal1-uvc-capture"
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="pointer-events-auto absolute bottom-1 left-1 right-1 rounded bg-amber-900/80 px-2 py-1 text-[10px] text-amber-100 hover:bg-amber-900"
        >
          PureThermal is in AGC mode. Click to set radiometric mode via GroupGets app.
        </a>
      )}

      {/* Hover crosshair + tooltip */}
      {hover && (
        <>
          <div
            className="pointer-events-none absolute h-px bg-cyan-300/60"
            style={{ left: 0, right: 0, top: hover.y }}
          />
          <div
            className="pointer-events-none absolute w-px bg-cyan-300/60"
            style={{ top: 0, bottom: 0, left: hover.x }}
          />
          <div
            className="pointer-events-none absolute rounded bg-black/80 px-2 py-1 font-mono text-xs text-white shadow"
            style={{ left: hover.x + 12, top: hover.y + 12 }}
          >
            {isCalibrated
              ? `${hover.celsius.toFixed(1)}°C`
              : `raw ${hover.raw}`}
          </div>
        </>
      )}

      {/* Pinned points */}
      {pins.map((p, i) => (
        <div
          key={i}
          className="pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%` }}
          onClick={(e) => removePin(i, e)}
          title="click to remove"
        >
          <div className="flex items-center gap-1">
            <div className="h-2 w-2 rounded-full bg-rose-400 ring-2 ring-rose-300" />
            <span className="rounded bg-rose-900/90 px-1.5 py-px text-[10px] font-mono text-white">
              {isCalibrated ? `${p.celsius.toFixed(1)}°C` : p.raw}
            </span>
          </div>
        </div>
      ))}

      {/* Clear-pins button */}
      {pins.length > 0 && (
        <button
          onClick={clearPins}
          className="pointer-events-auto absolute right-1 top-1 rounded border border-slate-700 bg-black/70 px-1.5 py-0.5 text-[10px] text-slate-300 hover:bg-slate-800"
        >
          clear {pins.length} pin{pins.length === 1 ? "" : "s"}
        </button>
      )}
    </div>
  );
}
