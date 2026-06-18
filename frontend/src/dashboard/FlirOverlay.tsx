import { RefObject, useEffect, useRef, useState } from "react";
import { radiometricSubscribe } from "../api/client";

export default function FlirOverlay({
  cameraId,
  videoRef,
}: {
  cameraId: string;
  videoRef: RefObject<HTMLVideoElement>;
}) {
  const matrixRef = useRef<{ w: number; h: number; data: Uint16Array } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; celsius: number } | null>(null);

  useEffect(() => {
    return radiometricSubscribe(cameraId, (w, h, data) => {
      matrixRef.current = { w, h, data };
    });
  }, [cameraId]);

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const m = matrixRef.current;
    const v = videoRef.current;
    if (!m || !v) return;
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width;
    const py = (e.clientY - rect.top) / rect.height;
    const mx = Math.min(m.w - 1, Math.max(0, Math.floor(px * m.w)));
    const my = Math.min(m.h - 1, Math.max(0, Math.floor(py * m.h)));
    const centiK = m.data[my * m.w + mx];
    const celsius = centiK / 100 - 273.15;
    setHover({ x: e.clientX - rect.left, y: e.clientY - rect.top, celsius });
  }

  return (
    <div
      ref={containerRef}
      className="pointer-events-auto absolute inset-0"
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
    >
      {hover && (
        <div
          className="pointer-events-none absolute rounded bg-black/70 px-2 py-1 text-xs text-white"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
        >
          {hover.celsius.toFixed(1)}°C
        </div>
      )}
    </div>
  );
}
