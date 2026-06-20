import { RefObject, useEffect, useRef, useState } from "react";
import { radiometricSubscribe } from "../api/client";

type Pin = { x: number; y: number; raw: number; ts: number };
type Stats = { rawMin: number; rawMax: number; rawCenter: number };
type Unit = "F" | "C" | "raw";

/**
 * Linear raw → Celsius conversion. Default values assume the Lepton is in
 * TLinear radiometric mode at 0.01 K resolution (raw is centi-Kelvin).
 *
 * If the camera is in AGC mode, the raw values are auto-stretched 14-bit
 * counts that don't map to temperature on their own — the user can fit a
 * 2-point calibration (scale + offset) against known references.
 */
type Cal = { scale: number; offset: number };
type RefPt = { raw: number; celsius: number };

const PIN_STORAGE_PREFIX = "camera_dash.flir.pins.";
const UNIT_STORAGE_KEY = "camera_dash.flir.unit";
const CAL_STORAGE_PREFIX = "camera_dash.flir.cal.";

const DEFAULT_CAL: Cal = { scale: 0.01, offset: -273.15 };

function rawToC(raw: number, cal: Cal): number {
  return raw * cal.scale + cal.offset;
}

function formatTemp(raw: number, unit: Unit, cal: Cal): string {
  if (!isFinite(raw)) return "—";
  if (unit === "raw") return String(raw);
  const c = rawToC(raw, cal);
  if (unit === "C") return `${c.toFixed(1)}°C`;
  return `${(c * 9 / 5 + 32).toFixed(1)}°F`;
}

function fitCal(p1: RefPt, p2: RefPt | null, prev: Cal): Cal {
  if (p2 && p2.raw !== p1.raw) {
    const scale = (p2.celsius - p1.celsius) / (p2.raw - p1.raw);
    const offset = p1.celsius - scale * p1.raw;
    return { scale, offset };
  }
  // 1-point: keep slope, shift offset so p1.raw maps to p1.celsius
  return { scale: prev.scale, offset: p1.celsius - prev.scale * p1.raw };
}

export default function FlirOverlay({
  cameraId,
  videoRef: _videoRef,
}: {
  cameraId: string;
  videoRef: RefObject<HTMLVideoElement>;
}) {
  const matrixRef = useRef<{ w: number; h: number; data: Uint16Array } | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; raw: number } | null>(null);
  const [pins, setPins] = useState<Pin[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(PIN_STORAGE_PREFIX + cameraId) || "[]");
    } catch { return []; }
  });
  const [stats, setStats] = useState<Stats | null>(null);
  const [unit, setUnit] = useState<Unit>(() => {
    const stored = localStorage.getItem(UNIT_STORAGE_KEY);
    return stored === "C" || stored === "F" || stored === "raw" ? stored : "F";
  });
  const [cal, setCal] = useState<Cal>(() => {
    try {
      const stored = localStorage.getItem(CAL_STORAGE_PREFIX + cameraId);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (typeof parsed.scale === "number" && typeof parsed.offset === "number") {
          return parsed;
        }
      }
    } catch { /* ignore */ }
    return DEFAULT_CAL;
  });
  const [showCal, setShowCal] = useState(false);
  const [refs, setRefs] = useState<[RefPt | null, RefPt | null]>([null, null]);
  const celsiusInputs: [
    React.RefObject<HTMLInputElement>,
    React.RefObject<HTMLInputElement>,
  ] = [useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null)];

  function persistCal(c: Cal) {
    setCal(c);
    localStorage.setItem(CAL_STORAGE_PREFIX + cameraId, JSON.stringify(c));
  }

  function cycleUnit(e: React.MouseEvent) {
    e.stopPropagation();
    const next: Unit = unit === "F" ? "C" : unit === "C" ? "raw" : "F";
    setUnit(next);
    localStorage.setItem(UNIT_STORAGE_KEY, next);
  }

  // Subscribe to radiometric WS + maintain rolling stats
  useEffect(() => {
    return radiometricSubscribe(cameraId, (w, h, data) => {
      matrixRef.current = { w, h, data };
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
        setStats({ rawMin: mn, rawMax: mx, rawCenter: center });
      }
    });
  }, [cameraId]);

  // Refresh pinned points' raw values as new frames arrive
  useEffect(() => {
    if (pins.length === 0) return;
    const t = setInterval(() => {
      const m = matrixRef.current;
      if (!m) return;
      setPins((prev) => prev.map((p) => {
        const mx = Math.min(m.w - 1, Math.max(0, Math.floor(p.x * m.w)));
        const my = Math.min(m.h - 1, Math.max(0, Math.floor(p.y * m.h)));
        return { ...p, raw: m.data[my * m.w + mx] };
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
    const { px, py, cx, cy } = eventToFrac(e);
    const m = matrixRef.current;
    let raw = NaN;
    if (m) {
      const mx = Math.min(m.w - 1, Math.max(0, Math.floor(px * m.w)));
      const my = Math.min(m.h - 1, Math.max(0, Math.floor(py * m.h)));
      raw = m.data[my * m.w + mx];
    }
    setHover({ x: cx, y: cy, raw });
  }

  function onClick(e: React.MouseEvent<HTMLDivElement>) {
    e.stopPropagation();
    const m = matrixRef.current;
    if (!m) return;
    const { px, py } = eventToFrac(e);
    const mx = Math.min(m.w - 1, Math.max(0, Math.floor(px * m.w)));
    const my = Math.min(m.h - 1, Math.max(0, Math.floor(py * m.h)));
    const raw = m.data[my * m.w + mx];

    if (showCal) {
      // Calibration mode: click captures into the next empty reference slot.
      // After both are filled, further clicks do nothing until a slot is cleared.
      const idx: 0 | 1 | null = refs[0] == null ? 0 : refs[1] == null ? 1 : null;
      if (idx == null) return;
      const slot: RefPt = { raw, celsius: NaN };
      setRefs(idx === 0 ? [slot, refs[1]] : [refs[0], slot]);
      // Focus the °C input so the user can immediately type the temperature
      setTimeout(() => celsiusInputs[idx].current?.focus(), 0);
      return;
    }

    // Default mode: drop a pin
    const next: Pin[] = [...pins, { x: px, y: py, raw, ts: Date.now() }];
    setPins(next);
    localStorage.setItem(PIN_STORAGE_PREFIX + cameraId, JSON.stringify(next));
  }

  function clearRef(idx: 0 | 1) {
    setRefs(idx === 0 ? [null, refs[1]] : [refs[0], null]);
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

  function setRefCelsius(idx: 0 | 1, value: string) {
    const c = parseFloat(value);
    const cur = refs[idx];
    if (!cur) return;
    const slot: RefPt = { raw: cur.raw, celsius: isFinite(c) ? c : NaN };
    setRefs(idx === 0 ? [slot, refs[1]] : [refs[0], slot]);
  }

  function applyCal() {
    const [r1, r2] = refs;
    if (!r1 || !isFinite(r1.celsius)) return;
    const next = fitCal(
      r1,
      r2 && isFinite(r2.celsius) ? r2 : null,
      cal
    );
    persistCal(next);
  }

  function resetCal() {
    persistCal(DEFAULT_CAL);
    setRefs([null, null]);
  }

  const isCustomCal = cal.scale !== DEFAULT_CAL.scale || cal.offset !== DEFAULT_CAL.offset;

  return (
    <div
      className="pointer-events-auto absolute inset-0 cursor-crosshair"
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
      onClick={onClick}
    >
      {/* Frame stats (top-left) */}
      {stats && (
        <div className="pointer-events-none absolute left-1 top-1 rounded bg-black/70 px-2 py-1 text-[10px] font-mono text-white shadow">
          <div>
            min {formatTemp(stats.rawMin, unit, cal)} · max {formatTemp(stats.rawMax, unit, cal)}
          </div>
          <div>center {formatTemp(stats.rawCenter, unit, cal)}</div>
          {isCustomCal && unit !== "raw" && (
            <div className="text-cyan-300">cal: ×{cal.scale.toExponential(2)} + {cal.offset.toFixed(2)}°C</div>
          )}
        </div>
      )}

      {/* Top-right control cluster: unit toggle + cal button */}
      <div className="absolute right-1 top-1 flex gap-1">
        <button
          onClick={cycleUnit}
          title="click to cycle °F → °C → raw"
          className="pointer-events-auto rounded border border-slate-700 bg-black/70 px-1.5 py-0.5 text-[10px] font-mono text-slate-200 hover:bg-slate-800"
        >
          {unit === "raw" ? "raw" : `°${unit}`}
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); setShowCal((v) => !v); }}
          title="calibrate raw → °C"
          className={`pointer-events-auto rounded border px-1.5 py-0.5 text-[10px] font-mono hover:bg-slate-800 ${
            showCal
              ? "border-cyan-500 bg-cyan-900/70 text-cyan-100"
              : "border-slate-700 bg-black/70 text-slate-200"
          }`}
        >
          cal
        </button>
      </div>

      {/* Calibration panel — positioned at the bottom so it occludes less of the image */}
      {showCal && (() => {
        const activeIdx: 0 | 1 | null = refs[0] == null ? 0 : refs[1] == null ? 1 : null;
        return (
          <div
            className="pointer-events-auto absolute bottom-1 left-1 right-1 rounded border border-slate-700 bg-slate-900/95 p-2 text-[11px] text-slate-100 shadow-lg"
            onClick={(e) => e.stopPropagation()}
            onMouseMove={(e) => e.stopPropagation()}
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="font-semibold text-cyan-300">Calibrate raw → °C</span>
              <span className="font-mono text-[10px] text-slate-400">
                C = raw × {cal.scale.toExponential(3)} + {cal.offset.toFixed(2)}
              </span>
            </div>
            <div className="mb-2 text-[10px] text-slate-400">
              {activeIdx == null
                ? "Both points captured. Type each °C, then apply."
                : <>Click a known-temperature spot on the image to set <span className="text-cyan-300">pt{activeIdx + 1}</span>, then type its °C.</>}
            </div>

            {([0, 1] as const).map((i) => {
              const r = refs[i];
              const isActive = activeIdx === i;
              return (
                <div key={i} className="mb-1 flex items-center gap-1">
                  <span className={`w-7 ${isActive ? "text-cyan-300" : "text-slate-400"}`}>
                    pt{i + 1}{isActive ? " ◀" : ""}
                  </span>
                  <span className="w-20 text-right font-mono text-slate-300">
                    {r ? `raw ${r.raw}` : isActive ? "click image…" : "—"}
                  </span>
                  <input
                    ref={celsiusInputs[i]}
                    type="number"
                    step="0.1"
                    placeholder="°C"
                    value={r && isFinite(r.celsius) ? r.celsius : ""}
                    disabled={!r}
                    onChange={(e) => setRefCelsius(i, e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") applyCal(); }}
                    className="w-16 rounded border border-slate-600 bg-slate-800 px-1 py-0.5 text-right font-mono text-slate-100 disabled:opacity-40"
                  />
                  <button
                    onClick={() => clearRef(i)}
                    disabled={!r}
                    className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300 hover:bg-slate-700 disabled:opacity-30"
                    title="clear this point"
                  >
                    ✕
                  </button>
                </div>
              );
            })}

            <div className="mt-2 flex gap-1">
              <button
                onClick={applyCal}
                disabled={!refs[0] || !isFinite(refs[0].celsius)}
                className="rounded border border-cyan-600 bg-cyan-800/60 px-2 py-0.5 text-[10px] text-cyan-100 hover:bg-cyan-700/60 disabled:opacity-40"
              >
                apply
              </button>
              <button
                onClick={resetCal}
                className="rounded border border-slate-600 bg-slate-800 px-2 py-0.5 text-[10px] hover:bg-slate-700"
                title="restore TLinear default (×0.01 + -273.15)"
              >
                reset
              </button>
              <button
                onClick={() => setShowCal(false)}
                className="ml-auto rounded border border-slate-700 bg-slate-800 px-2 py-0.5 text-[10px] hover:bg-slate-700"
              >
                close
              </button>
            </div>
          </div>
        );
      })()}

      {/* Hover crosshair + tooltip */}
      {hover && (
        <>
          <div
            className="pointer-events-none absolute"
            style={{
              left: 0, right: 0, top: hover.y - 1, height: 2,
              background: "#22d3ee",
              boxShadow: "0 0 0 1px rgba(0,0,0,0.6)",
              mixBlendMode: "difference",
            }}
          />
          <div
            className="pointer-events-none absolute"
            style={{
              top: 0, bottom: 0, left: hover.x - 1, width: 2,
              background: "#22d3ee",
              boxShadow: "0 0 0 1px rgba(0,0,0,0.6)",
              mixBlendMode: "difference",
            }}
          />
          <div
            className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full"
            style={{
              left: hover.x, top: hover.y, width: 10, height: 10,
              background: "#22d3ee",
              boxShadow: "0 0 0 2px rgba(0,0,0,0.6), 0 0 0 4px rgba(34,211,238,0.4)",
            }}
          />
          <div
            className="pointer-events-none absolute rounded bg-black/85 px-2 py-1 font-mono text-xs text-white shadow ring-1 ring-cyan-300/40"
            style={{ left: hover.x + 16, top: hover.y + 16 }}
          >
            {!isFinite(hover.raw) ? "waiting for thermal frame…" : formatTemp(hover.raw, unit, cal)}
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
              {formatTemp(p.raw, unit, cal)}
            </span>
          </div>
        </div>
      ))}

      {/* Clear-pins button — below the unit/cal row, hidden while cal panel is open */}
      {pins.length > 0 && !showCal && (
        <button
          onClick={clearPins}
          className="pointer-events-auto absolute right-1 top-9 rounded border border-slate-700 bg-black/70 px-1.5 py-0.5 text-[10px] text-slate-300 hover:bg-slate-800"
        >
          clear {pins.length} pin{pins.length === 1 ? "" : "s"}
        </button>
      )}
    </div>
  );
}
