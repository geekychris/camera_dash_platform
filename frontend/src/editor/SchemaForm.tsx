// Tailwind-native JSON Schema form. Renders one field per schema property,
// with type-appropriate inputs and inline validation. Replaces @rjsf/core in
// PropertiesPanel; far less code than rjsf for the (limited) schema shapes
// our node CONFIG_SCHEMAs actually use.
//
// Supported property shapes:
//   - string / string with `enum`
//   - number / integer with optional `minimum` / `maximum`
//   - boolean
//   - array of {string,integer,number} — entered as comma-separated text
//   - nested `object` with its own `properties`

import { useMemo } from "react";

type Json = unknown;

type Property = {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: Json;
  enum?: Json[];
  minimum?: number;
  maximum?: number;
  minItems?: number;
  maxItems?: number;
  items?: Property;
  properties?: Record<string, Property>;
  required?: string[];
};

export type Schema = {
  type?: string;
  required?: string[];
  properties?: Record<string, Property>;
};

export default function SchemaForm({
  schema,
  value,
  onChange,
}: {
  schema: Schema;
  value: Record<string, Json>;
  onChange: (next: Record<string, Json>) => void;
}) {
  const props = schema.properties ?? {};
  const required = useMemo(() => new Set(schema.required ?? []), [schema.required]);
  if (Object.keys(props).length === 0) {
    return <div className="text-xs italic text-slate-500">No configurable fields.</div>;
  }
  return (
    <div className="space-y-3">
      {Object.entries(props).map(([name, prop]) => (
        <Field
          key={name}
          name={name}
          prop={prop}
          required={required.has(name)}
          value={value[name]}
          onChange={(v) => onChange({ ...value, [name]: v })}
        />
      ))}
    </div>
  );
}

function Field({
  name, prop, required, value, onChange,
}: {
  name: string;
  prop: Property;
  required: boolean;
  value: Json;
  onChange: (v: Json) => void;
}) {
  const effective = value === undefined ? prop.default : value;
  const error = validate(prop, effective, required);
  const label = prop.title ?? name;
  const type = primaryType(prop.type);

  return (
    <div>
      <label className="mb-1 flex items-center gap-1 text-xs font-medium text-slate-300">
        <span>{label}</span>
        {required && <span className="text-rose-400" title="required">*</span>}
        {prop.enum && (
          <span className="text-[10px] uppercase tracking-wide text-slate-500">enum</span>
        )}
      </label>

      {renderInput(prop, type, effective, onChange)}

      {prop.description && (
        <div className="mt-1 text-[11px] leading-snug text-slate-500">{prop.description}</div>
      )}
      {error && (
        <div className="mt-1 text-[11px] text-rose-300">{error}</div>
      )}
    </div>
  );
}

function renderInput(prop: Property, type: string, value: Json, onChange: (v: Json) => void) {
  // enum → select (works for any base type)
  if (prop.enum && Array.isArray(prop.enum)) {
    return (
      <select
        className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100"
        value={String(value ?? "")}
        onChange={(e) => onChange(coerce(prop.enum?.find((x) => String(x) === e.target.value) ?? e.target.value, type))}
      >
        {prop.enum.map((v) => (
          <option key={String(v)} value={String(v)}>{String(v)}</option>
        ))}
      </select>
    );
  }

  if (type === "boolean") {
    return (
      <input
        type="checkbox"
        checked={Boolean(value)}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-violet-500 focus:ring-violet-500"
      />
    );
  }

  if (type === "integer" || type === "number") {
    const step = type === "integer" ? 1 : "any";
    return (
      <input
        type="number"
        className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100"
        value={value as number | string | undefined ?? ""}
        step={step}
        min={prop.minimum}
        max={prop.maximum}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") {
            onChange(undefined);
            return;
          }
          const n = type === "integer" ? parseInt(raw, 10) : parseFloat(raw);
          onChange(Number.isNaN(n) ? raw : n);
        }}
      />
    );
  }

  if (type === "array") {
    const itemType = primaryType(prop.items?.type) || "string";
    const arr = Array.isArray(value) ? value : [];
    const text = arr.join(", ");
    return (
      <input
        type="text"
        className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100"
        value={text}
        placeholder={itemType === "integer" || itemType === "number"
          ? "e.g. 0, 255, 0"
          : "comma-separated"}
        onChange={(e) => onChange(parseArray(e.target.value, itemType))}
      />
    );
  }

  if (type === "object" && prop.properties) {
    // Nested objects render inline with a thin left border so the hierarchy reads.
    const obj = (value && typeof value === "object") ? (value as Record<string, Json>) : {};
    return (
      <div className="ml-1 mt-1 border-l border-slate-800 pl-3">
        <SchemaForm
          schema={{ properties: prop.properties, required: prop.required }}
          value={obj}
          onChange={onChange as (next: Record<string, Json>) => void}
        />
      </div>
    );
  }

  return (
    <input
      type="text"
      className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100"
      value={(value as string | undefined) ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}
    />
  );
}

function primaryType(t: string | string[] | undefined): string {
  if (Array.isArray(t)) return t[0] ?? "string";
  return t ?? "string";
}

function coerce(v: Json, type: string): Json {
  if (type === "integer") {
    const n = parseInt(String(v), 10);
    return Number.isNaN(n) ? v : n;
  }
  if (type === "number") {
    const n = parseFloat(String(v));
    return Number.isNaN(n) ? v : n;
  }
  if (type === "boolean") return Boolean(v);
  return v;
}

function parseArray(raw: string, itemType: string): Json[] {
  const parts = raw.split(",").map((s) => s.trim()).filter((s) => s.length > 0);
  if (itemType === "integer") return parts.map((s) => parseInt(s, 10));
  if (itemType === "number") return parts.map((s) => parseFloat(s));
  return parts;
}

function validate(prop: Property, value: Json, required: boolean): string | null {
  const isEmpty = value === undefined || value === null || value === "" ||
    (Array.isArray(value) && value.length === 0);
  if (required && isEmpty) return "Required.";
  if (isEmpty) return null;

  const type = primaryType(prop.type);
  if (type === "integer" || type === "number") {
    if (typeof value !== "number" || Number.isNaN(value)) return "Must be a number.";
    if (type === "integer" && !Number.isInteger(value)) return "Must be an integer.";
    if (prop.minimum !== undefined && value < prop.minimum) return `Must be ≥ ${prop.minimum}.`;
    if (prop.maximum !== undefined && value > prop.maximum) return `Must be ≤ ${prop.maximum}.`;
  }
  if (prop.enum && !prop.enum.some((v) => v === value)) {
    return `Must be one of: ${prop.enum.map(String).join(", ")}.`;
  }
  if (type === "array") {
    if (!Array.isArray(value)) return "Must be a list.";
    const itemType = primaryType(prop.items?.type);
    if (itemType === "integer" || itemType === "number") {
      if (value.some((v) => typeof v !== "number" || Number.isNaN(v))) {
        return `Each value must be a ${itemType}.`;
      }
    }
    if (prop.minItems !== undefined && value.length < prop.minItems) {
      return `Need at least ${prop.minItems} item${prop.minItems === 1 ? "" : "s"}.`;
    }
    if (prop.maxItems !== undefined && value.length > prop.maxItems) {
      return `At most ${prop.maxItems} item${prop.maxItems === 1 ? "" : "s"}.`;
    }
  }
  return null;
}
