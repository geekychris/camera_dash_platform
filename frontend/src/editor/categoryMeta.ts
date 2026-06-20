// Single source of truth for per-category visual treatment in the editor.
//
// Used by the React Flow node body, the palette items, and the auto-generated
// description bar so they all agree on "what does a `condition` look like?".

export type CategoryMeta = {
  /** Tailwind classes for the node-on-canvas pill background + border. */
  bg: string;
  /** Tailwind classes for the small icon chip (palette + node header). */
  chip: string;
  /** Emoji glyph — readable in plain text, no extra fonts/sprites needed. */
  icon: string;
  /** Plain-text label for tooltips and listings. */
  label: string;
};

export const CATEGORIES: Record<string, CategoryMeta> = {
  source:    { bg: "bg-emerald-900 border-emerald-700", chip: "bg-emerald-800 text-emerald-200", icon: "📷", label: "source" },
  detector:  { bg: "bg-blue-900 border-blue-700",       chip: "bg-blue-800 text-blue-200",       icon: "🎯", label: "detector" },
  transform: { bg: "bg-violet-900 border-violet-700",   chip: "bg-violet-800 text-violet-200",   icon: "🔀", label: "transform" },
  condition: { bg: "bg-amber-900 border-amber-700",     chip: "bg-amber-800 text-amber-200",     icon: "⚖️", label: "condition" },
  broadcast: { bg: "bg-sky-900 border-sky-700",         chip: "bg-sky-800 text-sky-200",         icon: "📡", label: "broadcast" },
  sink:      { bg: "bg-rose-900 border-rose-700",       chip: "bg-rose-800 text-rose-200",       icon: "📥", label: "sink" },
  misc:      { bg: "bg-slate-800 border-slate-700",     chip: "bg-slate-700 text-slate-200",     icon: "•",   label: "misc" },
};

export function metaFor(category: string | undefined): CategoryMeta {
  if (!category) return CATEGORIES.misc;
  return CATEGORIES[category] ?? CATEGORIES.misc;
}
