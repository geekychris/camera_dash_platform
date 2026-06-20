import { useEffect, useState } from "react";
import { Node } from "@xyflow/react";
import { api, NodeDescriptor } from "../api/client";
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
  // Live camera list — used to render a dropdown for any `camera_id` field
  // instead of a free-text input. Refreshes when the editor loads; the user
  // can hit a node's properties panel after adding a camera and see it
  // appear in the menu without a hard reload.
  const [cameraIds, setCameraIds] = useState<string[] | null>(null);
  useEffect(() => {
    let alive = true;
    api.listCameras()
      .then((cs) => { if (alive) setCameraIds(cs.map((c) => c.id)); })
      .catch(() => { if (alive) setCameraIds([]); });
    return () => { alive = false; };
  }, [node?.id]);

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
  // Map every property name we want to dropdown-ify to its option list.
  // `camera_id` is the obvious one — could extend to e.g. `pipeline_id` or
  // model names later by adding entries here.
  const enumOverrides: Record<string, string[]> = {};
  if (cameraIds !== null) enumOverrides.camera_id = cameraIds;

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
          enumOverrides={enumOverrides}
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
