import { useMemo } from "react";
import { NodeDescriptor } from "../api/client";

export default function NodePalette({
  catalog,
  onAdd,
}: {
  catalog: NodeDescriptor[];
  onAdd: (n: NodeDescriptor) => void;
}) {
  const grouped = useMemo(() => {
    const g: Record<string, NodeDescriptor[]> = {};
    for (const n of catalog) (g[n.category] ||= []).push(n);
    return g;
  }, [catalog]);

  return (
    <div className="p-2 text-sm">
      <div className="mb-2 px-1 font-semibold text-slate-300">Nodes</div>
      {Object.entries(grouped).map(([cat, items]) => (
        <div key={cat} className="mb-3">
          <div className="px-1 text-xs uppercase tracking-wide text-slate-500">{cat}</div>
          {items.map((n) => (
            <button
              key={n.type_id}
              onClick={() => onAdd(n)}
              title={n.doc}
              className="block w-full truncate rounded px-2 py-1 text-left hover:bg-slate-800"
            >
              {n.type_id}
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
