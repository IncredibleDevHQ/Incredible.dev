// Picking one of a few options by how each looks: a tile per option, a small picture of it above
// its name, and under the tiles one line saying what the option under the pointer or the focus
// is (the chosen one's otherwise). The group is one tab stop: the arrow keys, Home and End move
// between the tiles without picking, and Enter or Space picks. Written for this house from notes
// on how such pickers behave; no other component's source is in it.
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";

export type Tile<T extends string> = { value: T; label: string; art: ReactNode; means: string; note?: string };

export function Tiles<T extends string>({
  options,
  value,
  onPick,
  label,
  columns = 3,
  disabled = false,
}: {
  options: Tile<T>[];
  value: T;
  onPick: (value: T) => void;
  label: string;
  columns?: number;
  disabled?: boolean;
}) {
  const uid = useId();
  const [shown, setShown] = useState<T | null>(null);
  const [stop, setStop] = useState<T | null>(null);
  const tiles = useRef(new Map<T, HTMLButtonElement>());
  const has = (v: T | null) => v !== null && options.some((o) => o.value === v);
  // The tab stop: the tile the focus was last on, else the chosen one, else the first.
  const tabStop = has(stop) ? stop : has(value) ? value : (options[0]?.value ?? null);

  const go = (from: T, to: "next" | "back" | "first" | "last") => {
    const at = options.findIndex((o) => o.value === from);
    const n = options.length;
    const index = to === "first" ? 0 : to === "last" ? n - 1 : (at + (to === "next" ? 1 : -1) + n) % n;
    tiles.current.get(options[index].value)?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, at: T) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    // a page written right to left reads its rows the other way
    const rtl = getComputedStyle(e.currentTarget).direction === "rtl";
    const to =
      e.key === "ArrowDown" || e.key === (rtl ? "ArrowLeft" : "ArrowRight")
        ? "next"
        : e.key === "ArrowUp" || e.key === (rtl ? "ArrowRight" : "ArrowLeft")
          ? "back"
          : e.key === "Home"
            ? "first"
            : e.key === "End"
              ? "last"
              : null;
    if (!to) return;
    e.preventDefault();
    e.stopPropagation();
    go(at, to);
  };

  const current = options.find((o) => o.value === shown) ?? options.find((o) => o.value === value);
  return (
    <div className="ep-tiles-wrap">
      <div className="ep-tiles" role="radiogroup" aria-label={label} aria-disabled={disabled || undefined} style={{ "--cols": columns } as CSSProperties} onPointerLeave={() => setShown(null)}>
        {options.map((o) => (
          <button
            key={o.value}
            ref={(el) => {
              if (el) tiles.current.set(o.value, el);
              else tiles.current.delete(o.value);
            }}
            type="button"
            role="radio"
            className="ep-tile"
            aria-checked={o.value === value}
            aria-describedby={`${uid}-${o.value}`}
            aria-disabled={disabled || undefined}
            tabIndex={o.value === tabStop ? 0 : -1}
            onClick={() => !disabled && o.value !== value && onPick(o.value)}
            onPointerEnter={() => setShown(o.value)}
            onFocus={() => {
              setShown(o.value);
              setStop(o.value);
            }}
            onBlur={() => setShown(null)}
            onKeyDown={(e) => onKey(e, o.value)}
          >
            <span className="ep-tile-art" aria-hidden="true">
              {o.art}
            </span>
            <span className="ep-tile-name">
              {o.label}
              {o.note && <small>{o.note}</small>}
            </span>
            <span id={`${uid}-${o.value}`} hidden>
              {o.means}
            </span>
          </button>
        ))}
      </div>
      {/* each tile names its meaning to a screen reader; this line is for the eye */}
      {current && (
        <Swap swapKey={current.value} className="ep-tiles-means" hidden>
          <b>{current.label}</b> {current.means}
        </Swap>
      )}
    </div>
  );
}

const SWAP_MS = 380;

// Words that change in place: the old ones blur and fade out as the new ones blur and fade in,
// and the box glides from the old height to the new instead of jumping. With reduced motion the
// words just change.
export function Swap({ swapKey, children, className, hidden }: { swapKey: string; children: ReactNode; className?: string; hidden?: boolean }) {
  const box = useRef<HTMLSpanElement>(null);
  const [gone, setGone] = useState<{ key: string; node: ReactNode } | null>(null);
  const was = useRef<{ key: string; node: ReactNode; height: number } | null>(null);
  const timer = useRef(0);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const before = was.current;
    const calm = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!before || before.key === swapKey || calm) {
      was.current = { key: swapKey, node: children, height: el.getBoundingClientRect().height };
      return;
    }
    // From the height it has now (part way through a glide, or at rest), to the new words' own.
    const from = el.style.height ? el.getBoundingClientRect().height : before.height;
    el.style.transition = "none";
    el.style.height = "auto";
    const to = el.getBoundingClientRect().height;
    el.style.height = `${from}px`;
    void el.offsetHeight;
    el.style.transition = `height ${SWAP_MS}ms cubic-bezier(0.16, 1, 0.3, 1)`;
    el.style.height = `${to}px`;
    el.dataset.gliding = "";
    setGone({ key: before.key, node: before.node });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      el.style.height = "";
      el.style.transition = "";
      delete el.dataset.gliding;
      setGone(null);
      was.current = { key: swapKey, node: children, height: el.getBoundingClientRect().height };
    }, SWAP_MS + 30);
    was.current = { key: swapKey, node: children, height: to };
  });
  useEffect(() => () => window.clearTimeout(timer.current), []);

  return (
    <span ref={box} className={`ep-swap ${className ?? ""}`} aria-hidden={hidden || undefined}>
      {gone && gone.key !== swapKey && (
        <span className="ep-swap-out" aria-hidden="true" inert>
          {gone.node}
        </span>
      )}
      <span key={swapKey} className="ep-swap-in">
        {children}
      </span>
    </span>
  );
}
