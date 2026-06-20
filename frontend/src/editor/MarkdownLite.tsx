// Tiny markdown renderer for the node-docstring subset our code uses.
//
// Pulls in no library; handles exactly what we write in Python docstrings:
//
//   - Paragraphs (blank-line separated)
//   - Indented or unindented numbered (`1. foo`) and bulleted (`- foo`,
//     `* foo`) lists, with paragraph wrap inside the item
//   - Headers: leading `#`, `##`, `###`
//   - Inline `code` (single backtick) and ``code`` (double backtick, the
//     reStructuredText flavour Sphinx-style docstrings sprinkle around)
//   - Inline **bold**
//   - A bare-URL → link
//
// Skips fancier markdown (tables, blockquotes, fenced code blocks). When a
// docstring needs more, we'll switch to a library. Until then this keeps
// the bundle small and the rendering predictable.

import { Fragment, useMemo } from "react";

const NUMBERED_LIST = /^(\s*)(\d+)\.\s+(.*)$/;
const BULLETED_LIST = /^(\s*)[-*]\s+(.*)$/;
const HEADER        = /^(#{1,3})\s+(.+)$/;

type Block =
  | { kind: "p"; text: string }
  | { kind: "h"; level: 1 | 2 | 3; text: string }
  | { kind: "list"; items: string[] };

function blockify(raw: string): Block[] {
  const lines = raw.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let para: string[] = [];
  let listItems: string[] | null = null;

  const flushPara = () => {
    if (para.length) {
      blocks.push({ kind: "p", text: para.join(" ").trim() });
      para = [];
    }
  };
  const flushList = () => {
    if (listItems && listItems.length) {
      blocks.push({ kind: "list", items: listItems });
    }
    listItems = null;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      flushPara();
      flushList();
      continue;
    }
    const h = trimmed.match(HEADER);
    if (h) {
      flushPara();
      flushList();
      blocks.push({ kind: "h", level: h[1].length as 1 | 2 | 3, text: h[2] });
      continue;
    }
    const nm = trimmed.match(NUMBERED_LIST);
    const bm = trimmed.match(BULLETED_LIST);
    if (nm || bm) {
      flushPara();
      if (!listItems) listItems = [];
      listItems.push((nm ? nm[3] : bm![2]).trim());
      continue;
    }
    // Continuation of a list item (indented under a previous list line).
    if (listItems && /^\s/.test(line)) {
      listItems[listItems.length - 1] += " " + trimmed;
      continue;
    }
    flushList();
    para.push(trimmed);
  }
  flushPara();
  flushList();
  return blocks;
}

// Inline pass — bold, code (single + double backtick), links. Done last.
function renderInline(text: string, keyBase: string): React.ReactNode {
  // Order matters: double-backtick first so it doesn't get eaten by single.
  const tokens: { type: "text" | "code" | "bold" | "link"; value: string; href?: string }[] = [];
  let i = 0;
  while (i < text.length) {
    // Double-backtick code: `` text ``
    if (text.startsWith("``", i)) {
      const end = text.indexOf("``", i + 2);
      if (end !== -1) {
        tokens.push({ type: "code", value: text.slice(i + 2, end) });
        i = end + 2;
        continue;
      }
    }
    // Single-backtick code: `text`
    if (text[i] === "`") {
      const end = text.indexOf("`", i + 1);
      if (end !== -1) {
        tokens.push({ type: "code", value: text.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }
    // Bold: **text**
    if (text.startsWith("**", i)) {
      const end = text.indexOf("**", i + 2);
      if (end !== -1) {
        tokens.push({ type: "bold", value: text.slice(i + 2, end) });
        i = end + 2;
        continue;
      }
    }
    // Bare URL → link.
    if (text.startsWith("http://", i) || text.startsWith("https://", i)) {
      const m = text.slice(i).match(/^https?:\/\/[^\s)]+/);
      if (m) {
        tokens.push({ type: "link", value: m[0], href: m[0] });
        i += m[0].length;
        continue;
      }
    }
    // Accumulate plain text into the previous text token (or open a new one).
    const last = tokens[tokens.length - 1];
    if (last?.type === "text") last.value += text[i];
    else tokens.push({ type: "text", value: text[i] });
    i++;
  }

  return tokens.map((t, idx) => {
    const k = `${keyBase}-${idx}`;
    switch (t.type) {
      case "code":
        return <code key={k} className="rounded bg-slate-800 px-1 text-amber-300">{t.value}</code>;
      case "bold":
        return <strong key={k} className="text-slate-100">{t.value}</strong>;
      case "link":
        return (
          <a key={k} href={t.href} target="_blank" rel="noopener noreferrer"
             className="text-blue-300 underline hover:text-blue-200">
            {t.value}
          </a>
        );
      default:
        return <Fragment key={k}>{t.value}</Fragment>;
    }
  });
}

export default function MarkdownLite({ source, className }: { source: string; className?: string }) {
  const blocks = useMemo(() => blockify(source), [source]);
  return (
    <div className={className}>
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "h": {
            const sizes = { 1: "text-base font-semibold", 2: "text-sm font-semibold", 3: "text-xs font-semibold uppercase tracking-wide" } as const;
            return <div key={i} className={`mt-2 ${sizes[b.level]} text-slate-100`}>{renderInline(b.text, `h${i}`)}</div>;
          }
          case "list":
            return (
              <ul key={i} className="ml-4 list-disc space-y-0.5">
                {b.items.map((it, j) => <li key={j}>{renderInline(it, `l${i}-${j}`)}</li>)}
              </ul>
            );
          case "p":
            return <p key={i} className="leading-snug">{renderInline(b.text, `p${i}`)}</p>;
        }
      })}
    </div>
  );
}
