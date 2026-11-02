// A flow of cards in columns, each after everything it is made from, with lines from a card's
// right edge to what is made from it. The lines are drawn from where the cards really are, after
// layout, and again whenever one of them changes size (an image loading, a note opening).
import { useCallback, useLayoutEffect, useRef, useState } from "react";

export type Edge = { from: string; to: string; waiting?: boolean };
export type Line = Edge & { d: string };

export function useLines(box: React.RefObject<HTMLElement | null>, edges: Edge[], anchor = 22): Line[] {
  const [lines, setLines] = useState<Line[]>([]);
  const drawn = useRef("");
  const measure = useCallback(() => {
    const el = box.current;
    if (!el) return;
    const node = (id: string) => el.querySelector<HTMLElement>(`[data-node="${CSS.escape(id)}"]`);
    const out: Line[] = [];
    for (const edge of edges) {
      const a = node(edge.from);
      const b = node(edge.to);
      if (!a || !b) continue;
      const x1 = a.offsetLeft + a.offsetWidth;
      const y1 = a.offsetTop + anchor;
      const x2 = b.offsetLeft;
      const y2 = b.offsetTop + anchor;
      const dx = Math.max(24, (x2 - x1) / 2);
      out.push({ ...edge, d: `M${x1} ${y1}C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}` });
    }
    const key = out.map((l) => `${l.from}>${l.to}:${l.d}:${l.waiting ? 1 : 0}`).join("|");
    if (key !== drawn.current) {
      drawn.current = key;
      setLines(out);
    }
  }, [box, edges, anchor]);
  useLayoutEffect(measure);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(el);
    el.querySelectorAll("[data-node]").forEach((n) => observer.observe(n));
    return () => observer.disconnect();
  });
  return lines;
}

export function Lines({ lines, hot }: { lines: Line[]; hot?: string | null }) {
  return (
    <svg className="flow-lines" aria-hidden="true">
      {lines.map((l) => (
        <path
          key={`${l.from}>${l.to}`}
          d={l.d}
          className={[l.waiting ? "waiting" : "", hot && (l.from === hot || l.to === hot) ? "lit" : ""].join(" ")}
        />
      ))}
    </svg>
  );
}

/** Items in columns by how far they are from the start: each after everything it is made from. */
export function columnsOf<T extends { id: string; sources: string[] }>(items: T[]): T[][] {
  const byId = new Map(items.map((i) => [i.id, i]));
  const depth = new Map<string, number>();
  const visit = (item: T, seen: Set<string>): number => {
    const known = depth.get(item.id);
    if (known !== undefined) return known;
    if (seen.has(item.id)) return 1;
    seen.add(item.id);
    const parents = item.sources.map((s) => byId.get(s)).filter((p): p is T => p !== undefined);
    const d = parents.length ? 1 + Math.max(...parents.map((p) => visit(p, seen))) : 1;
    depth.set(item.id, d);
    return d;
  };
  const columns: T[][] = [];
  for (const item of items) (columns[visit(item, new Set()) - 1] ??= []).push(item);
  return columns.filter(Boolean);
}
