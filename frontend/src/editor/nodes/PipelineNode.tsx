import { useState } from "react";
import { Handle, NodeProps, Position } from "@xyflow/react";
import { NodeDescriptor } from "../../api/client";
import { metaFor } from "../categoryMeta";
import NodeHelpPopover from "../NodeHelpPopover";

type Data = { type: string; config: Record<string, unknown>; descriptor?: NodeDescriptor };

const PORT_COLOR: Record<string, string> = {
  frame: "#3b82f6",
  depth_frame: "#0ea5e9",
  detections: "#10b981",
  event: "#f59e0b",
  trigger: "#ef4444",
};

export default function PipelineNode({ data }: NodeProps) {
  const d = data as Data;
  const desc = d.descriptor;
  const inputs = desc?.inputs ?? [];
  const outputs = desc?.outputs ?? [];
  const meta = metaFor(desc?.category);
  const [anchor, setAnchor] = useState<DOMRect | null>(null);

  return (
    <>
      <div
        className={`relative min-w-44 rounded border ${meta.bg} px-3 py-2 text-xs text-white shadow`}
        onMouseEnter={(e) => setAnchor((e.currentTarget as HTMLDivElement).getBoundingClientRect())}
        onMouseLeave={() => setAnchor(null)}
      >
        <div className="flex items-center gap-1.5 font-semibold">
          <span className="text-sm leading-none" title={meta.label}>{meta.icon}</span>
          <span className="truncate">{d.type}</span>
        </div>
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
      {desc && <NodeHelpPopover descriptor={desc} anchor={anchor} />}
    </>
  );
}
