import Form from "@rjsf/core";
import validator from "@rjsf/validator-ajv8";
import { Node } from "@xyflow/react";
import { NodeDescriptor } from "../api/client";

type NodeData = { type: string; config: Record<string, unknown>; descriptor?: NodeDescriptor };

export default function PropertiesPanel({
  node,
  onChange,
}: {
  node: Node | null;
  onChange: (cfg: Record<string, unknown>) => void;
}) {
  if (!node) return <div className="p-4 text-sm text-slate-500">Select a node to edit its config.</div>;
  const data = node.data as NodeData;
  const schema = (data.descriptor?.config_schema as object) ?? { type: "object", properties: {} };
  return (
    <div className="h-full overflow-auto">
      <div className="border-b border-slate-800 px-3 py-2 text-sm font-semibold">
        {data.type} <span className="text-slate-500">· {node.id}</span>
      </div>
      <div className="p-3 text-sm">
        <Form
          schema={schema}
          validator={validator}
          formData={data.config}
          onChange={(e) => onChange(e.formData)}
          uiSchema={{ "ui:submitButtonOptions": { norender: true } }}
          liveValidate
        />
      </div>
    </div>
  );
}
