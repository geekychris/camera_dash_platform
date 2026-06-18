import { useEffect, useRef, useState } from "react";
import { whepConnect } from "../api/client";

/**
 * Modal polygon editor — captures a still from the live stream, lets the user
 * click points, then outputs JSON pixel coordinates to paste into a
 * `condition.zone` (or `condition.line_crossing` / `transform.privacy_mask`) node.
 */
export default function PolygonEditor({
  videoUrl, width, height, onClose,
}: {
  videoUrl: string; width: number; height: number; onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [points, setPoints] = useState<[number, number][]>([]);
  const [naturalSize, setNaturalSize] = useState<{ w: number; h: number }>({ w: width, h: height });
  const [stillCaptured, setStillCaptured] = useState(false);

  useEffect(() => {
    let pc: RTCPeerConnection | null = null;
    if (videoRef.current) {
      whepConnect(videoUrl, videoRef.current).then((p) => (pc = p)).catch(console.warn);
    }
    return () => { pc?.close(); };
  }, [videoUrl]);

  useEffect(() => {
    if (!videoRef.current) return;
    const v = videoRef.current;
    function update() {
      if (v.videoWidth && v.videoHeight) setNaturalSize({ w: v.videoWidth, h: v.videoHeight });
    }
    v.addEventListener("loadedmetadata", update);
    v.addEventListener("playing", update);
    return () => {
      v.removeEventListener("loadedmetadata", update);
      v.removeEventListener("playing", update);
    };
  }, []);

  // Draw the polygon overlay on the canvas every animation frame
  useEffect(() => {
    let raf = 0;
    function draw() {
      const cnv = canvasRef.current;
      if (!cnv) return;
      const ctx = cnv.getContext("2d")!;
      ctx.clearRect(0, 0, cnv.width, cnv.height);
      if (points.length > 0) {
        ctx.strokeStyle = "#22d3ee";
        ctx.fillStyle = "rgba(34, 211, 238, 0.2)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(points[0][0], points[0][1]);
        for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1]);
        if (points.length > 2) ctx.closePath();
        ctx.fill();
        ctx.stroke();
        for (const [x, y] of points) {
          ctx.fillStyle = "#22d3ee";
          ctx.beginPath();
          ctx.arc(x, y, 5, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [points]);

  function captureStill() {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    const cnv = document.createElement("canvas");
    cnv.width = v.videoWidth; cnv.height = v.videoHeight;
    cnv.getContext("2d")!.drawImage(v, 0, 0);
    const img = cnv.toDataURL("image/png");
    const bg = document.getElementById("polygon-still");
    if (bg) (bg as HTMLImageElement).src = img;
    setStillCaptured(true);
  }

  function onClick(e: React.MouseEvent<HTMLCanvasElement>) {
    const cnv = canvasRef.current!;
    const rect = cnv.getBoundingClientRect();
    const px = (e.clientX - rect.left) * (cnv.width / rect.width);
    const py = (e.clientY - rect.top) * (cnv.height / rect.height);
    // Right-click finishes; left-click adds
    if (e.button === 2) return;
    setPoints((p) => [...p, [Math.round(px), Math.round(py)]]);
  }

  function undo() { setPoints((p) => p.slice(0, -1)); }
  function clear() { setPoints([]); }
  async function copyToClipboard() {
    const json = JSON.stringify(points);
    try { await navigator.clipboard.writeText(json); alert("Copied to clipboard"); }
    catch { prompt("Copy this:", json); }
  }

  // Render the canvas at the video's native size so coordinates are pixel-accurate
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           className="relative max-h-[90vh] max-w-[90vw] overflow-hidden rounded-lg border border-slate-700 bg-slate-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900 px-3 py-2 text-xs">
          <span className="text-slate-300">Polygon editor — click to add points · {naturalSize.w}×{naturalSize.h}px</span>
          <span className="flex gap-2">
            <button onClick={captureStill}
                    className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800">
              Freeze frame
            </button>
            <button onClick={undo}
                    className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800">Undo</button>
            <button onClick={clear}
                    className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800">Clear</button>
            <button onClick={copyToClipboard}
                    className="rounded bg-cyan-700 px-2 py-0.5 hover:bg-cyan-600">Copy coords</button>
            <button onClick={onClose}
                    className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800">Close</button>
          </span>
        </div>
        <div className="relative" style={{ maxWidth: "85vw", maxHeight: "75vh" }}>
          {stillCaptured && (
            <img id="polygon-still" alt="" className="block max-h-[75vh] max-w-[85vw]"
                 style={{ aspectRatio: `${naturalSize.w}/${naturalSize.h}` }} />
          )}
          {!stillCaptured && (
            <video ref={videoRef} autoPlay muted playsInline
                   className="block max-h-[75vh] max-w-[85vw]"
                   style={{ aspectRatio: `${naturalSize.w}/${naturalSize.h}` }} />
          )}
          <canvas
            ref={canvasRef}
            width={naturalSize.w}
            height={naturalSize.h}
            onClick={onClick}
            onContextMenu={(e) => e.preventDefault()}
            className="absolute inset-0 h-full w-full cursor-crosshair"
          />
        </div>
        <div className="border-t border-slate-800 bg-slate-950 p-2 text-xs text-slate-400">
          <div>{points.length} point(s) — paste into a <code className="rounded bg-slate-800 px-1">condition.zone</code>'s
            <code className="ml-1 rounded bg-slate-800 px-1">polygon</code>:</div>
          <pre className="mt-1 overflow-auto rounded bg-black p-2 text-[11px] text-emerald-300">
{JSON.stringify(points)}
          </pre>
        </div>
      </div>
    </div>
  );
}
