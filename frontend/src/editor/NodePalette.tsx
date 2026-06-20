import { useMemo, useState } from "react";
import { NodeDescriptor } from "../api/client";
import { metaFor } from "./categoryMeta";
import NodeHelpPopover from "./NodeHelpPopover";

const CATEGORY_ORDER = ["source", "transform", "detector", "condition", "broadcast", "sink", "misc"];

function compareCategories(a: string, b: string): number {
  const ia = CATEGORY_ORDER.indexOf(a);
  const ib = CATEGORY_ORDER.indexOf(b);
  if (ia === -1 && ib === -1) return a.localeCompare(b);
  if (ia === -1) return 1;
  if (ib === -1) return -1;
  return ia - ib;
}

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
    return Object.entries(g).sort(([a], [b]) => compareCategories(a, b));
  }, [catalog]);

  const [hovered, setHovered] = useState<NodeDescriptor | null>(null);
  const [anchor, setAnchor] = useState<DOMRect | null>(null);

  return (
    <>
      <div className="p-2 text-sm">
        <div className="mb-2 px-1 font-semibold text-slate-300">Nodes</div>
        {grouped.map(([cat, items]) => {
          const meta = metaFor(cat);
          return (
            <div key={cat} className="mb-3">
              <div className="flex items-center gap-1.5 px-1 text-xs uppercase tracking-wide text-slate-500">
                <span className="text-sm">{meta.icon}</span>
                <span>{cat}</span>
              </div>
              {items.map((n) => (
                <button
                  key={n.type_id}
                  onClick={() => onAdd(n)}
                  onMouseEnter={(e) => {
                    setAnchor((e.currentTarget as HTMLButtonElement).getBoundingClientRect());
                    setHovered(n);
                  }}
                  onMouseLeave={() => setHovered((h) => (h?.type_id === n.type_id ? null : h))}
                  className="flex w-full items-center gap-1.5 truncate rounded px-2 py-1 text-left hover:bg-slate-800"
                >
                  <span className="text-xs opacity-80">{meta.icon}</span>
                  <span className="truncate">{n.type_id}</span>
                </button>
              ))}
            </div>
          );
        })}
      </div>
      <NodeHelpPopover descriptor={hovered} anchor={anchor} />
    </>
  );
}
