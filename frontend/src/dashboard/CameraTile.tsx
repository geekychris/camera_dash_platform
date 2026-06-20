import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, CameraInfo, whepConnect } from "../api/client";
import FlirOverlay from "./FlirOverlay";
import KinectDepthOverlay from "./KinectDepthOverlay";
import PolygonEditor from "./PolygonEditor";
import StreamShareMenu from "./StreamShareMenu";

export default function CameraTile({
  camera,
  badge,
  pipelineId,
}: {
  camera: CameraInfo;
  badge?: string;
  pipelineId?: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const wheelTargetRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [showPolyEditor, setShowPolyEditor] = useState(false);
  const [recording, setRecording] = useState(false);
  const [shareAnchor, setShareAnchor] = useState<DOMRect | null>(null);
  const [restarting, setRestarting] = useState(false);

  async function restart(e: React.MouseEvent) {
    e.stopPropagation();
    setRestarting(true);
    try { await api.restartCamera(camera.id); }
    catch (err) { alert(`restart failed: ${err}`); }
    finally { setRestarting(false); }
  }

  // Flash the REC indicator when a clip starts for this camera (via SSE listening for 'clip_started' kind)
  useEffect(() => {
    const es = new EventSource("/api/events/stream");
    es.addEventListener("event", (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data);
        if (d.camera_id !== camera.id) return;
        if (d.kind === "clip_started" || d.kind === "temperature_gate"
            || d.kind === "zone_enter" || d.kind === "zone_dwell"
            || d.kind === "metadata_match" || d.kind === "counter"
            || d.kind === "line_crossing") {
          setRecording(true);
          setTimeout(() => setRecording(false), 4000);
        }
      } catch { /* ignore */ }
    });
    return () => es.close();
  }, [camera.id]);

  async function snapshot(e: React.MouseEvent) {
    e.stopPropagation();
    try { await api.snapshot(camera.id); }
    catch (err) { alert(`snapshot failed: ${err}`); }
  }

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    whepConnect(camera.urls.webrtc, video)
      .then((pc) => (pcRef.current = pc))
      .catch((e) => console.warn("WHEP failed for", camera.id, e));
    return () => {
      pcRef.current?.close();
      pcRef.current = null;
    };
  }, [camera.id, camera.urls.webrtc]);

  // React's onWheel synthetic events are passive in modern React, so preventDefault
  // logs warnings + does nothing. Attach a native listener with passive:false.
  useEffect(() => {
    const el = wheelTargetRef.current;
    if (!el) return;
    function handler(e: WheelEvent) {
      e.preventDefault();
      setZoom((z) => Math.min(8, Math.max(1, z + (e.deltaY < 0 ? 0.2 : -0.2))));
    }
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  return (
    <div className="flex h-full w-full flex-col">
      <div className="drag-handle flex h-7 shrink-0 cursor-move items-center justify-between border-b border-slate-800 bg-slate-950 px-3 text-xs select-none">
        <span className="flex min-w-0 items-center gap-2 truncate">
          {badge && (
            pipelineId ? (
              <Link
                to={`/editor/${pipelineId}`}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => e.stopPropagation()}
                title={`Edit pipeline ${pipelineId}`}
                className="rounded bg-violet-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-violet-100 hover:bg-violet-600"
              >
                {badge} ↗
              </Link>
            ) : (
              <span className="rounded bg-violet-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-violet-100">
                {badge}
              </span>
            )
          )}
          {recording && (
            <span className="flex items-center gap-1 rounded bg-red-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-white animate-pulse">
              <span className="h-1.5 w-1.5 rounded-full bg-white" /> rec
            </span>
          )}
          <span className="truncate">{camera.label || camera.id}</span>
        </span>
        <span className="ml-2 flex shrink-0 items-center gap-1 text-slate-500">
          <span>{Math.round(zoom * 100)}%</span>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); setZoom(1); }}
            className="rounded border border-slate-700 px-1 text-[10px] hover:bg-slate-800"
          >reset</button>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={snapshot}
            title="Capture snapshot (saved to /clips)"
            className="rounded border border-slate-700 px-1 text-[10px] hover:bg-slate-800"
          >📷</button>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              const rect = (e.currentTarget as HTMLButtonElement).getBoundingClientRect();
              setShareAnchor((cur) => (cur ? null : rect));
            }}
            title="Get stream URLs + player commands (VLC, ffplay, ffmpeg)"
            className="rounded border border-slate-700 px-1 text-[10px] hover:bg-slate-800"
          >🔗</button>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={restart}
            disabled={restarting}
            title="Restart this camera (drops the driver's stale handle — use after a hardware replug)"
            className={`rounded border border-slate-700 px-1 text-[10px] hover:bg-slate-800 disabled:opacity-50 ${restarting ? "animate-spin" : ""}`}
          >↻</button>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); setShowPolyEditor(true); }}
            title="Draw polygon (copy coords to a condition.zone node)"
            className="rounded border border-slate-700 px-1 text-[10px] hover:bg-slate-800"
          >▱</button>
          <span>{camera.kind}{camera.is_thermal ? " · thermal" : ""}</span>
        </span>
      </div>
      <div
        ref={wheelTargetRef}
        className="relative min-h-0 flex-1 overflow-hidden bg-black"
      >
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          className="absolute inset-0 m-auto max-h-full max-w-full"
          style={{ transform: `scale(${zoom})`, transformOrigin: "center center", transition: "transform 0.1s" }}
        />
        {camera.is_thermal && <FlirOverlay cameraId={camera.id} videoRef={videoRef} />}
        {camera.has_depth && <KinectDepthOverlay cameraId={camera.id} videoRef={videoRef} />}
      </div>
      {shareAnchor && (
        <StreamShareMenu
          id={camera.id}
          urls={camera.urls}
          anchor={shareAnchor}
          onClose={() => setShareAnchor(null)}
        />
      )}
      {showPolyEditor && (
        <PolygonEditor
          videoUrl={camera.urls.webrtc}
          width={Number(camera.params.width) || 1280}
          height={Number(camera.params.height) || 720}
          onClose={() => setShowPolyEditor(false)}
        />
      )}
    </div>
  );
}
