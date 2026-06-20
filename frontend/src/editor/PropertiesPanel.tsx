import { Node } from "@xyflow/react";
import { NodeDescriptor } from "../api/client";
import { metaFor } from "./categoryMeta";
import SchemaForm, { Schema } from "./SchemaForm";

type NodeData = { type: string; config: Record<string, unknown>; descriptor?: NodeDescriptor };

export default function PropertiesPanel({
  node,
  onChange,
}: {
  node: Node | null;
  onChange: (cfg: Record<string, unknown>) => void;
}) {
  if (!node) {
    return (
      <div className="p-4 text-sm text-slate-500">
        Select a node to edit its config.
      </div>
    );
  }
  const data = node.data as NodeData;
  const schema = (data.descriptor?.config_schema as Schema) ?? { type: "object", properties: {} };
  const meta = metaFor(data.descriptor?.category);
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-slate-800 bg-slate-900 px-3 py-2 text-sm">
        <span className="text-base">{meta.icon}</span>
        <span className="font-semibold text-slate-100">{data.type}</span>
        <span className="text-slate-500">· {node.id}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <SchemaForm
          schema={schema}
          value={data.config || {}}
          onChange={onChange}
        />
        {data.descriptor?.doc && (
          <div className="mt-4 border-t border-slate-800 pt-3 text-[11px] leading-snug text-slate-400 whitespace-pre-wrap">
            {data.descriptor.doc}
          </div>
        )}
      </div>
    </div>
  );
}
