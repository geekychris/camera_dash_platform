import { useEffect, useRef, useState } from "react";

type Urls = { webrtc: string; hls: string; rtsp: string };

/**
 * Floating menu listing every transport URL for a camera/derived stream,
 * plus ready-to-paste command lines for the players most people reach for
 * (VLC, ffplay, OBS via copy-paste, ffmpeg record). Each row has a copy
 * button.
 *
 * RTSP is the most universally useful — works in VLC, ffmpeg, OBS, MPV,
 * gstreamer. HLS is the one that plays in a browser without WebRTC
 * signalling. WebRTC is included for completeness but is only useful in a
 * browser that can handle the WHEP handshake.
 */
export default function StreamShareMenu({
  id,
  urls,
  anchor,
  onClose,
}: {
  id: string;
  urls: Urls;
  anchor: DOMRect | null;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // Track which row was just copied so we can flash a "Copied!" indicator.
  const [copied, setCopied] = useState<string | null>(null);

  // Click-outside / Esc to close.
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  if (!anchor) return null;

  const W = 420;
  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  const vh = typeof window !== "undefined" ? window.innerHeight : 768;
  // Pin under the trigger; flip left if it would clip the right edge.
  const left = Math.min(vw - W - 8, Math.max(8, anchor.right - W));
  const top = Math.min(vh - 360, anchor.bottom + 4);

  async function copy(label: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setCopied((c) => (c === label ? null : c)), 1200);
    } catch {
      // Fallback for older browsers / non-HTTPS contexts.
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      setCopied(label);
      setTimeout(() => setCopied((c) => (c === label ? null : c)), 1200);
    }
  }

  const rtsp = urls.rtsp;
  const hls = urls.hls;
  const webrtc = urls.webrtc;

  const rows: { label: string; value: string; help?: string }[] = [
    { label: "RTSP URL", value: rtsp, help: "Universal — VLC, OBS, ffmpeg, MPV, GStreamer" },
    { label: "HLS URL", value: hls, help: "Browser-friendly, ~3 s latency" },
    { label: "WebRTC URL (WHEP)", value: webrtc, help: "Lowest latency; needs a WebRTC-capable client" },
    { label: "VLC", value: `vlc ${rtsp}`, help: "Open in VLC from the terminal" },
    { label: "ffplay", value: `ffplay -fflags nobuffer -flags low_delay ${rtsp}`,
      help: "Tuned for low latency" },
    { label: "Record (ffmpeg)",
      value: `ffmpeg -rtsp_transport tcp -i ${rtsp} -c copy ${id.replace(/[/]/g, "_")}.mp4`,
      help: "No re-encode; output sized to source bitrate" },
    { label: "Snapshot (ffmpeg)",
      value: `ffmpeg -rtsp_transport tcp -i ${rtsp} -frames:v 1 ${id.replace(/[/]/g, "_")}.jpg`,
      help: "Grab a single JPEG and exit" },
    { label: "mpv", value: `mpv --profile=low-latency ${rtsp}`,
      help: "MPV is often nicer than VLC on Linux" },
  ];

  return (
    <div
      ref={ref}
      className="fixed z-50 rounded-lg border border-slate-700 bg-slate-900 p-3 shadow-xl"
      style={{ top, left, width: W }}
    >
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold text-slate-100">
          Share <span className="font-mono text-violet-300">{id}</span>
        </div>
        <button
          onClick={onClose}
          className="rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800"
        >
          esc
        </button>
      </div>
      <ul className="max-h-[24rem] space-y-2 overflow-y-auto text-xs">
        {rows.map((r) => (
          <li key={r.label}>
            <div className="flex items-center gap-2">
              <span className="w-28 shrink-0 text-slate-400">{r.label}</span>
              <code className="grow truncate rounded bg-slate-950 px-2 py-1 font-mono text-amber-300">
                {r.value}
              </code>
              <button
                onClick={() => copy(r.label, r.value)}
                className={`shrink-0 rounded border px-2 py-1 text-[10px] ${
                  copied === r.label
                    ? "border-emerald-500 bg-emerald-700 text-white"
                    : "border-slate-700 text-slate-200 hover:bg-slate-800"
                }`}
              >
                {copied === r.label ? "Copied!" : "Copy"}
              </button>
            </div>
            {r.help && <div className="ml-30 mt-0.5 pl-30 text-[10px] text-slate-500" style={{ marginLeft: "7rem" }}>{r.help}</div>}
          </li>
        ))}
      </ul>
    </div>
  );
}
