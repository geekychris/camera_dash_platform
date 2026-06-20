import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, CameraInfo, PipelineDef } from "../api/client";

export default function CameraManager() {
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [discovered, setDiscovered] = useState<{ index: number; name: string; device?: string; hintKind?: string }[]>([]);
  const [form, setForm] = useState({ id: "", kind: "uvc", label: "", device_index: 0, device: "" });
  const [pipelines, setPipelines] = useState<PipelineDef[]>([]);
  const [cloningFor, setCloningFor] = useState<string | null>(null);

  async function refresh() {
    setCameras(await api.listCameras());
  }

  useEffect(() => {
    refresh();
    api.listPipelines().then(setPipelines).catch(() => { /* non-fatal */ });
  }, []);

  async function discover() {
    const r = await api.discoverCameras();
    // Tag each entry with its driver hint so kindForDevice() can prefer the
    // libfreenect-enumerated Kinects (which carry no friendly name) over name
    // sniffing.
    const merged = [
      ...r.uvc.map((d) => ({ ...d, hintKind: undefined })),
      ...(r.kinect ?? []).map((d) => ({ ...d, hintKind: "kinect_v1" })),
    ];
    setDiscovered(merged);
  }

  function kindForDevice(name: string, hint?: string): string {
    if (hint) return hint;
    const n = name.toLowerCase();
    if (n.includes("purethermal") || n.includes("flir") || n.includes("lepton")) return "flir_lepton";
    if (n.includes("kinect") || n.includes("xbox nui")) return "kinect_v1";
    return "uvc";
  }

  function existingCameraIds(): Set<string> {
    return new Set(cameras.map((c) => c.id));
  }

  function selectDiscovered(d: { index: number; name: string; device?: string; hintKind?: string }) {
    const kind = kindForDevice(d.name, d.hintKind);
    // Suggest a sensible id; if it collides, append the device index.
    const taken = existingCameraIds();
    const slug =
      kind === "flir_lepton" ? "flir" :
      kind === "kinect_v1" ? "kinect" :
      "cam";
    let id = `${slug}_${d.index}`;
    if (taken.has(id)) id = `${id}_alt`;
    setForm({ id, kind, label: d.name, device_index: d.index, device: d.device || "" });
  }

  async function add() {
    if (!form.id) return;
    // Prefer the explicit /dev/video<N> path when discover reported one
    // (Linux only — macOS doesn't expose a stable path). Pinning by path
    // sidesteps the sequence-index vs kernel-index drift that caused the
    // "added flir_1 → opened FLIR #1's metadata node" bug on the Pi.
    const useDevicePath = form.device && form.device.startsWith("/dev/");
    const baseDevice: Record<string, unknown> = useDevicePath
      ? { device: form.device }
      : { device_index: form.device_index };
    const params: Record<string, unknown> =
      form.kind === "uvc"
        ? { ...baseDevice, width: 1280, height: 720, fps: 30 }
        : form.kind === "kinect_v1"
          ? { device_index: form.device_index }
          : form.kind === "flir_lepton"
            ? { ...baseDevice, fps: 9 }
            : { fps: 9 };
    await api.addCamera({ id: form.id, kind: form.kind, label: form.label, params });
    setForm({ id: "", kind: "uvc", label: "", device_index: 0, device: "" });
    refresh();
  }

  async function remove(id: string) {
    await api.removeCamera(id);
    refresh();
  }

  async function rename(c: CameraInfo) {
    const label = prompt(`Label for ${c.id}?`, c.label || "");
    if (label == null) return;
    await api.setLabel(c.id, label);
    refresh();
  }

  return (
    <div className="h-full overflow-auto p-6">
      <h2 className="mb-4 text-xl font-semibold">Cameras</h2>

      <section className="mb-8 rounded border border-slate-800 bg-slate-900 p-4">
        <h3 className="mb-3 font-semibold">Add camera</h3>
        <div className="grid grid-cols-5 gap-2 text-sm">
          <input
            className="rounded bg-slate-950 px-2 py-1"
            placeholder="id (e.g. cam-front)"
            value={form.id}
            onChange={(e) => setForm({ ...form, id: e.target.value })}
          />
          <select
            className="rounded bg-slate-950 px-2 py-1"
            value={form.kind}
            onChange={(e) => setForm({ ...form, kind: e.target.value })}
          >
            <option value="uvc">USB (UVC)</option>
            <option value="flir_lepton">FLIR Lepton</option>
            <option value="kinect_v1">Kinect 360 (v1)</option>
          </select>
          <input
            className="rounded bg-slate-950 px-2 py-1"
            placeholder="label"
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.target.value })}
          />
          {(form.kind === "uvc" || form.kind === "kinect_v1" || form.kind === "flir_lepton") && (
            <input
              type="number"
              className="rounded bg-slate-950 px-2 py-1"
              placeholder="device_index"
              value={form.device_index}
              onChange={(e) => setForm({ ...form, device_index: Number(e.target.value) })}
            />
          )}
          <button className="rounded bg-blue-600 px-3 py-1 hover:bg-blue-500" onClick={add}>
            Add
          </button>
        </div>
        <div className="mt-3 flex items-center gap-3 text-sm">
          <button className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800" onClick={discover}>
            Discover devices
          </button>
          {discovered.length === 0 && (
            <span className="text-slate-500">
              Click discover to list every camera the host can see. Each entry below prefills the form.
            </span>
          )}
        </div>
        {discovered.length > 0 && (
          <div className="mt-3 grid grid-cols-1 gap-1 text-sm sm:grid-cols-2 lg:grid-cols-3">
            {discovered.map((d) => {
              const kind = kindForDevice(d.name, d.hintKind);
              const taken = existingCameraIds().has(`${kind === "flir_lepton" ? "flir" : kind === "kinect_v1" ? "kinect" : "cam"}_${d.index}`);
              return (
                <button
                  key={`${kind}:${d.index}`}
                  onClick={() => selectDiscovered(d)}
                  className="flex flex-col items-start gap-1 rounded border border-slate-800 bg-slate-950 px-2 py-1.5 text-left hover:border-violet-700 hover:bg-slate-900"
                  title="Click to prefill the form with this device"
                >
                  <div className="flex items-center gap-2 text-xs">
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-amber-300">#{d.index}</span>
                    <span className={`rounded px-1.5 py-0.5 uppercase ${
                      kind === "flir_lepton" ? "bg-rose-900 text-rose-200"
                      : kind === "kinect_v1" ? "bg-sky-900 text-sky-200"
                      : "bg-emerald-900 text-emerald-200"
                    }`}>{kind}</span>
                    {taken && <span className="text-[10px] text-slate-500">(already added)</span>}
                  </div>
                  <div className="truncate text-slate-200">{d.name}</div>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-3 font-semibold">Configured</h3>
        <table className="w-full text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th className="py-2 pr-4">ID</th>
              <th className="pr-4">Label</th>
              <th className="pr-4">Kind</th>
              <th className="pr-4">Running</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {cameras.map((c) => (
              <>
                <tr key={c.id} className="border-t border-slate-800">
                  <td className="py-2 pr-4 font-mono">{c.id}</td>
                  <td className="pr-4">{c.label}</td>
                  <td className="pr-4">{c.kind}</td>
                  <td className="pr-4">{c.running ? "yes" : "no"}</td>
                  <td className="pr-4 text-right">
                    <button
                      className="mr-2 text-violet-300 hover:underline"
                      onClick={() => setCloningFor((cur) => (cur === c.id ? null : c.id))}
                    >
                      Clone pipeline →
                    </button>
                    <button className="mr-2 text-blue-300 hover:underline" onClick={() => rename(c)}>
                      Rename
                    </button>
                    <button className="text-red-300 hover:underline" onClick={() => remove(c.id)}>
                      Remove
                    </button>
                  </td>
                </tr>
                {cloningFor === c.id && (
                  <tr key={`${c.id}-clone`} className="border-t border-slate-800 bg-slate-950">
                    <td colSpan={5} className="px-2 py-3">
                      <ClonePipelinePanel
                        targetCameraId={c.id}
                        pipelines={pipelines}
                        onDone={() => { setCloningFor(null); api.listPipelines().then(setPipelines); }}
                      />
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function ClonePipelinePanel({
  targetCameraId,
  pipelines,
  onDone,
}: {
  targetCameraId: string;
  pipelines: PipelineDef[];
  onDone: () => void;
}) {
  const [sourcePid, setSourcePid] = useState<string>("");
  const [sourceCams, setSourceCams] = useState<string[] | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [newId, setNewId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pickPipeline(pid: string) {
    setSourcePid(pid);
    setError(null);
    setSourceCams(null);
    setMapping({});
    if (!pid) return;
    setNewId(`${pid}_${targetCameraId}`);
    try {
      const cams = await api.pipelineSourceCameras(pid);
      setSourceCams(cams);
      // Default mapping: every source camera → the target camera. For
      // single-source pipelines (the common case) the user just submits.
      setMapping(Object.fromEntries(cams.map((c) => [c, targetCameraId])));
    } catch (e) {
      setError(String(e));
    }
  }

  async function submit() {
    if (!sourcePid || !newId) return;
    setBusy(true);
    setError(null);
    try {
      await api.clonePipeline(sourcePid, {
        new_id: newId,
        camera_map: mapping,
        enabled: false,
      });
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-slate-400">Clone pipeline:</span>
        <select
          className="rounded bg-slate-900 px-2 py-1"
          value={sourcePid}
          onChange={(e) => pickPipeline(e.target.value)}
        >
          <option value="">— pick a pipeline —</option>
          {pipelines.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name || p.id} ({p.id})
            </option>
          ))}
        </select>
        <span className="text-slate-400">→ new id:</span>
        <input
          className="rounded bg-slate-900 px-2 py-1"
          placeholder="new_pipeline_id"
          value={newId}
          onChange={(e) => setNewId(e.target.value)}
        />
      </div>

      {sourceCams && sourceCams.length === 0 && (
        <div className="text-amber-300">
          This pipeline has no <code>source.*</code> nodes that reference a camera_id; the clone will
          be an exact copy with no rebinding.
        </div>
      )}
      {sourceCams && sourceCams.length > 0 && (
        <div>
          <div className="mb-1 text-slate-400">Rewire each source camera:</div>
          <div className="space-y-1">
            {sourceCams.map((cam) => (
              <div key={cam} className="flex items-center gap-2">
                <code className="rounded bg-slate-800 px-1 text-amber-300">{cam}</code>
                <span className="text-slate-500">→</span>
                <input
                  className="rounded bg-slate-900 px-2 py-1"
                  value={mapping[cam] || ""}
                  onChange={(e) => setMapping({ ...mapping, [cam]: e.target.value })}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {error && <div className="text-rose-300">{error}</div>}

      <div className="flex items-center gap-2">
        <button
          className="rounded bg-violet-600 px-3 py-1 hover:bg-violet-500 disabled:opacity-50"
          onClick={submit}
          disabled={busy || !sourcePid || !newId}
        >
          {busy ? "Cloning…" : "Clone"}
        </button>
        <button
          className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800"
          onClick={onDone}
        >
          Cancel
        </button>
        {sourcePid && (
          <Link
            to={`/editor/${sourcePid}`}
            className="text-xs text-slate-400 hover:underline"
            title="Open source pipeline in the editor"
          >
            view source ↗
          </Link>
        )}
      </div>
    </div>
  );
}
