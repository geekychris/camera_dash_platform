import { useEffect, useState } from "react";
import { NodeDescriptor } from "../api/client";

type SchemaProp = { type?: string; description?: string; default?: unknown; enum?: unknown[] };
type Schema = { properties?: Record<string, SchemaProp>; required?: string[] };

function summarizeSchema(schema: unknown): { name: string; required: boolean; description: string }[] {
  const s = (schema || {}) as Schema;
  const required = new Set(s.required || []);
  const props = s.properties || {};
  return Object.entries(props).map(([name, p]) => ({
    name,
    required: required.has(name),
    description: (p.description || "").trim(),
  }));
}

/**
 * Floating help card for a node descriptor. Positioned to the right of the
 * anchor rect by default; flips left when it would overflow the viewport.
 *
 * Caller owns hover state — pass `anchor` (DOMRect) when shown, `null` to hide.
 * Pointer-events disabled so the card never steals mouse interactions.
 */
export default function NodeHelpPopover({
  descriptor,
  anchor,
}: {
  descriptor: NodeDescriptor | null;
  anchor: DOMRect | null;
}) {
  const [vw, setVw] = useState(typeof window !== "undefined" ? window.innerWidth : 1024);
  const [vh, setVh] = useState(typeof window !== "undefined" ? window.innerHeight : 768);
  useEffect(() => {
    function onResize() { setVw(window.innerWidth); setVh(window.innerHeight); }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  if (!descriptor || !anchor) return null;
  const W = 360;
  const flipLeft = anchor.right + 8 + W > vw;
  const left = flipLeft ? Math.max(8, anchor.left - W - 8) : anchor.right + 8;
  const top = Math.max(8, Math.min(anchor.top, vh - 360));

  const fields = summarizeSchema(descriptor.config_schema);
  return (
    <div
      className="pointer-events-none fixed z-50 max-h-[36rem] overflow-hidden rounded-lg border border-slate-700 bg-slate-900 p-3 text-xs leading-relaxed text-slate-200 shadow-xl"
      style={{ top, left, width: W }}
    >
      <div className="mb-1 font-mono text-sm font-semibold text-violet-300">{descriptor.type_id}</div>
      {descriptor.doc ? (
        <div className="mb-2 whitespace-pre-wrap text-slate-300">{descriptor.doc}</div>
      ) : (
        <div className="mb-2 italic text-slate-500">No description.</div>
      )}
      {descriptor.inputs.length > 0 && (
        <div className="mb-1 text-slate-400">
          <span className="font-semibold text-slate-300">in:</span>{" "}
          {descriptor.inputs.map((p) => `${p.name}:${p.port_type}`).join(", ")}
        </div>
      )}
      {descriptor.outputs.length > 0 && (
        <div className="mb-2 text-slate-400">
          <span className="font-semibold text-slate-300">out:</span>{" "}
          {descriptor.outputs.map((p) => `${p.name}:${p.port_type}`).join(", ")}
        </div>
      )}
      {fields.length > 0 && (
        <div className="border-t border-slate-800 pt-2">
          <div className="mb-1 font-semibold text-slate-300">Config</div>
          <ul className="space-y-1">
            {fields.slice(0, 10).map((f) => (
              <li key={f.name}>
                <span className="font-mono text-amber-300">{f.name}</span>
                {f.required && <span className="ml-1 text-rose-400">*</span>}
                {f.description && <span className="ml-1 text-slate-400">— {f.description}</span>}
              </li>
            ))}
            {fields.length > 10 && (
              <li className="text-slate-500">…and {fields.length - 10} more</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
