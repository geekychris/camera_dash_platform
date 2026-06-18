import { useEffect, useState } from "react";
import { api, CameraInfo } from "../api/client";

export default function CameraManager() {
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [discovered, setDiscovered] = useState<{ index: number; name: string }[]>([]);
  const [form, setForm] = useState({ id: "", kind: "uvc", label: "", device_index: 0 });

  async function refresh() {
    setCameras(await api.listCameras());
  }

  useEffect(() => {
    refresh();
  }, []);

  async function discover() {
    const r = await api.discoverCameras();
    setDiscovered(r.uvc);
  }

  async function add() {
    if (!form.id) return;
    const params: Record<string, unknown> =
      form.kind === "uvc" ? { device_index: form.device_index, width: 1280, height: 720, fps: 30 } : { fps: 9 };
    await api.addCamera({ id: form.id, kind: form.kind, label: form.label, params });
    setForm({ id: "", kind: "uvc", label: "", device_index: 0 });
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
          </select>
          <input
            className="rounded bg-slate-950 px-2 py-1"
            placeholder="label"
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.target.value })}
          />
          {form.kind === "uvc" && (
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
            Discover UVC
          </button>
          {discovered.length > 0 && (
            <span className="text-slate-400">
              {discovered.map((d) => `[${d.index}] ${d.name}`).join("  ·  ")}
            </span>
          )}
        </div>
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
              <tr key={c.id} className="border-t border-slate-800">
                <td className="py-2 pr-4 font-mono">{c.id}</td>
                <td className="pr-4">{c.label}</td>
                <td className="pr-4">{c.kind}</td>
                <td className="pr-4">{c.running ? "yes" : "no"}</td>
                <td className="pr-4 text-right">
                  <button className="mr-2 text-blue-300 hover:underline" onClick={() => rename(c)}>
                    Rename
                  </button>
                  <button className="text-red-300 hover:underline" onClick={() => remove(c.id)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
