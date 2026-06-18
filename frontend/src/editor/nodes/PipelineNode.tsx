import { Handle, NodeProps, Position } from "@xyflow/react";
import { NodeDescriptor } from "../../api/client";

type Data = { type: string; config: Record<string, unknown>; descriptor?: NodeDescriptor };

const PORT_COLOR: Record<string, string> = {
  frame: "#3b82f6",
  detections: "#10b981",
  event: "#f59e0b",
  trigger: "#ef4444",
};

const CATEGORY_BG: Record<string, string> = {
  source: "bg-emerald-900 border-emerald-700",
  detector: "bg-blue-900 border-blue-700",
  transform: "bg-violet-900 border-violet-700",
  condition: "bg-amber-900 border-amber-700",
  sink: "bg-rose-900 border-rose-700",
  misc: "bg-slate-800 border-slate-700",
};

export default function PipelineNode({ data }: NodeProps) {
  const d = data as Data;
  const desc = d.descriptor;
  const inputs = desc?.inputs ?? [];
  const outputs = desc?.outputs ?? [];
  const bg = CATEGORY_BG[desc?.category ?? "misc"] ?? CATEGORY_BG.misc;
  return (
    <div className={`relative min-w-44 rounded border ${bg} px-3 py-2 text-xs text-white shadow`}>
      <div className="font-semibold">{d.type}</div>
      <div className="mt-2 grid grid-cols-2 gap-x-2">
        <div>
          {inputs.map((p, i) => (
            <div key={p.name} className="relative my-1 pl-3">
              <Handle
                id={p.name}
                type="target"
                position={Position.Left}
                style={{ background: PORT_COLOR[p.port_type] ?? "#888", top: 18 + i * 16 }}
              />
              <span>{p.name}</span>
            </div>
          ))}
        </div>
        <div className="text-right">
          {outputs.map((p, i) => (
            <div key={p.name} className="relative my-1 pr-3">
              <span>{p.name}</span>
              <Handle
                id={p.name}
                type="source"
                position={Position.Right}
                style={{ background: PORT_COLOR[p.port_type] ?? "#888", top: 18 + i * 16 }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
