import { useEffect, useMemo, useState } from "react";
import { api, CameraInfo } from "../api/client";
import { RECIPES, Recipe, RecipeEdge, RecipeField, RecipeNode } from "./recipes";

/**
 * Modal for "Insert recipe" — pick a recipe, fill the small form, hit Insert.
 * Returned graph chunk is wired but not laid out; the caller is responsible
 * for positioning the new nodes and (typically) calling auto-layout.
 *
 * Right pane shows the form for the focused recipe; left pane is a
 * categorised list of all recipes. Camera dropdowns are populated from
 * /api/cameras on mount so the user picks by label, not by typing an id.
 */
export default function RecipesModal({
  open,
  onClose,
  onInsert,
}: {
  open: boolean;
  onClose: () => void;
  onInsert: (chunk: { nodes: RecipeNode[]; edges: RecipeEdge[] }) => void;
}) {
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [active, setActive] = useState<Recipe>(RECIPES[0]);
  const [values, setValues] = useState<Record<string, unknown>>({});

  useEffect(() => {
    if (!open) return;
    api.listCameras().then(setCameras).catch(() => setCameras([]));
  }, [open]);

  // Initialise the form values from the recipe's defaults whenever the
  // focused recipe changes.
  useEffect(() => {
    const seed: Record<string, unknown> = {};
    for (const f of active.fields) {
      if ("default" in f && f.default !== undefined) seed[f.name] = f.default;
      else if (f.type === "strings") seed[f.name] = [];
      else if (f.type === "string") seed[f.name] = "";
      else if (f.type === "number") seed[f.name] = 0;
      else if (f.type === "camera") seed[f.name] = "";
    }
    setValues(seed);
  }, [active.id]);

  const byCategory = useMemo(() => {
    const m = new Map<string, Recipe[]>();
    for (const r of RECIPES) {
      const list = m.get(r.category) ?? [];
      list.push(r);
      m.set(r.category, list);
    }
    return Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, []);

  const missing = useMemo(() => {
    return active.fields.filter((f) => {
      if (f.type === "camera" && !values[f.name]) return true;
      return false;
    });
  }, [active, values]);

  function setField(name: string, v: unknown) {
    setValues((s) => ({ ...s, [name]: v }));
  }

  function insert() {
    let counter = 0;
    const id = (typeId: string) => {
      counter += 1;
      // Match PipelineEditor.newNodeId: lowercase + underscore, but namespace
      // with the recipe id so concurrent inserts don't collide.
      return `${typeId.replace(/[^a-z0-9]/g, "_")}_${active.id}_${counter}_${Math.random()
        .toString(36).slice(2, 5)}`;
    };
    const chunk = active.build(values, { id });
    onInsert(chunk);
    onClose();
  }

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
      onClick={onClose}
    >
      <div
        className="flex h-[640px] w-[920px] max-w-full overflow-hidden rounded-lg border border-slate-700 bg-slate-900 text-sm shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Recipe list */}
        <div className="w-64 shrink-0 overflow-y-auto border-r border-slate-800 bg-slate-950">
          <div className="border-b border-slate-800 px-3 py-2 font-semibold">Recipes</div>
          {byCategory.map(([cat, rs]) => (
            <div key={cat}>
              <div className="border-b border-slate-800/60 bg-slate-900 px-3 py-1 text-xs uppercase tracking-wide text-slate-400">
                {cat}
              </div>
              {rs.map((r) => (
                <button
                  key={r.id}
                  onClick={() => setActive(r)}
                  className={`block w-full border-b border-slate-800/60 px-3 py-2 text-left hover:bg-slate-800 ${
                    r.id === active.id ? "bg-slate-800" : ""
                  }`}
                >
                  <div className="font-medium text-slate-100">{r.name}</div>
                  <div className="mt-0.5 line-clamp-2 text-xs text-slate-400">{r.description}</div>
                </button>
              ))}
            </div>
          ))}
        </div>

        {/* Form */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-start justify-between border-b border-slate-800 px-4 py-3">
            <div>
              <div className="text-base font-semibold">{active.name}</div>
              <div className="mt-1 text-xs text-slate-400">{active.description}</div>
            </div>
            <button
              onClick={onClose}
              className="rounded px-2 py-0.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {active.fields.map((f) => (
              <Field
                key={f.name}
                field={f}
                value={values[f.name]}
                cameras={cameras}
                onChange={(v) => setField(f.name, v)}
              />
            ))}
          </div>

          <div className="flex items-center justify-between border-t border-slate-800 bg-slate-950 px-4 py-3">
            <div className="text-xs text-slate-400">
              {missing.length > 0
                ? `Pick: ${missing.map((m) => m.label).join(", ")}`
                : "Inserts a connected sub-graph; existing nodes are not touched."}
            </div>
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                onClick={insert}
                disabled={missing.length > 0}
                className="rounded bg-blue-600 px-3 py-1 text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Insert
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({
  field,
  value,
  cameras,
  onChange,
}: {
  field: RecipeField;
  value: unknown;
  cameras: CameraInfo[];
  onChange: (v: unknown) => void;
}) {
  const labelEl = (
    <label className="mb-1 block text-xs font-medium text-slate-300">
      {field.label}
      {"required" in field && field.required && <span className="ml-1 text-rose-400">*</span>}
    </label>
  );
  const descEl =
    "description" in field && field.description ? (
      <div className="mt-1 text-xs text-slate-500">{field.description}</div>
    ) : null;
  switch (field.type) {
    case "camera":
      return (
        <div>
          {labelEl}
          <select
            value={(value as string) ?? ""}
            onChange={(e) => onChange(e.target.value)}
            className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
          >
            <option value="">— pick —</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label || c.id} ({c.kind})
              </option>
            ))}
          </select>
          {descEl}
        </div>
      );
    case "string":
      return (
        <div>
          {labelEl}
          <input
            value={(value as string) ?? ""}
            onChange={(e) => onChange(e.target.value)}
            className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
          />
          {descEl}
        </div>
      );
    case "number":
      return (
        <div>
          {labelEl}
          <input
            type="number"
            value={(value as number) ?? 0}
            min={"min" in field ? field.min : undefined}
            max={"max" in field ? field.max : undefined}
            step="any"
            onChange={(e) => onChange(parseFloat(e.target.value))}
            className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
          />
          {descEl}
        </div>
      );
    case "select":
      return (
        <div>
          {labelEl}
          <select
            value={(value as string) ?? field.default ?? field.options[0]}
            onChange={(e) => onChange(e.target.value)}
            className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
          >
            {field.options.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
          {descEl}
        </div>
      );
    case "strings": {
      const arr = (value as string[]) ?? [];
      return (
        <div>
          {labelEl}
          <input
            value={arr.join(", ")}
            onChange={(e) =>
              onChange(
                e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              )
            }
            className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
            placeholder="comma-separated"
          />
          {descEl}
        </div>
      );
    }
    default:
      return null;
  }
}
