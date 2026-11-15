// affectUI's Popover (https://www.affectui.com), a free item under the MIT licence
// (licenses/affectui-MIT.txt), as it comes; app.css gives it the house's colours through `--aui-*`.
import { useEffect, useId, useLayoutEffect, useRef, type ComponentPropsWithoutRef, type ReactNode, type Ref, type RefObject } from "react";

/*
 * Popover – a single self-contained file.
 * A small floating card attached to its trigger: a short form, a few settings, an explanation. It opens on the side
 * you ask for and flips to the other side (or edge) when there is no room, so it is always fully reachable; it lives
 * in the top layer, so no card's overflow cuts it. A press outside, Escape or tabbing away closes it, and the focus
 * goes back to the trigger. It fades and scales in from the side it is attached to.
 * The styles are injected below, so no extra files are needed.
 */

export type PopoverProps = Omit<ComponentPropsWithoutRef<"div">, "title" | "children"> & {
  open: boolean;
  /** Called on a press outside, Escape, or when the focus leaves – set open to false here */
  onClose: () => void;
  children?: ReactNode;
  /** Where it opens; it flips to the other side when there is no room */
  side?: "bottom" | "top" | "right" | "left";
  /** Which edges line up: start (left, or top beside it) · center · end */
  align?: "start" | "center" | "end";
  /** Gap to the trigger in px */
  offset?: number;
  /** The element it is attached to – by default its parent element (wrap trigger and Popover in one element) */
  anchor?: RefObject<HTMLElement | null>;
  /** A heading at the top – it also names the popover */
  title?: ReactNode;
  /** A quiet line under the title – read out with it */
  description?: ReactNode;
  /** The card's width – by default it fits its content */
  width?: number | string;
  /** Moves the focus to the first control inside when it opens (or onto the card when there is none) */
  focusOnOpen?: boolean;
  /** Only the placing and the open/close: no card, padding or type of its own – your className draws it */
  unstyled?: boolean;
  ref?: Ref<HTMLDivElement>;
};

export function Popover({
  open,
  onClose,
  children,
  side = "bottom",
  align = "start",
  offset = 6,
  anchor,
  title,
  description,
  width,
  focusOnOpen = true,
  unstyled,
  className,
  style,
  role = "dialog",
  ref,
  ...rest
}: PopoverProps) {
  const uid = useId();
  const titleId = `${uid}-title`;
  const descId = `${uid}-desc`;
  const panel = useRef<HTMLDivElement | null>(null);
  const close = useRef(onClose);
  close.current = onClose;
  // Open from the start (a demo, a restored view) leaves the focus where it is – only an opening moves it
  const wasClosed = useRef(!open);
  if (!open) wasClosed.current = true;

  const anchorEl = () => anchor?.current ?? panel.current?.parentElement ?? null;
  const inside = (n: Node | null) => !!n && (!!panel.current?.contains(n) || !!anchorEl()?.contains(n));

  // Into the top layer and next to the anchor, before paint; it follows on scroll and resize
  useLayoutEffect(() => {
    const el = panel.current;
    if (!open || !el) return;
    showLayer(el);
    const update = () => {
      const a = anchorEl();
      if (a) place(el, a.getBoundingClientRect(), side, align, offset);
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    ro?.observe(el);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      ro?.disconnect();
      hideLayer(el);
    };
  }, [open, side, align, offset]); // eslint-disable-line react-hooks/exhaustive-deps

  // The focus moves in; however it closes, if the focus was inside, the trigger gets it back
  useEffect(() => {
    const el = panel.current;
    if (!open || !el) return;
    if (focusOnOpen && wasClosed.current && !el.contains(document.activeElement)) (firstControl(el) ?? el).focus({ preventScroll: true });
    const trigger = triggerOf(anchorEl(), el);
    let within = el.contains(document.activeElement);
    const into = () => (within = true);
    const away = (e: FocusEvent) => (within = !!e.relatedTarget && el.contains(e.relatedTarget as Node));
    el.addEventListener("focusin", into);
    el.addEventListener("focusout", away);
    return () => {
      el.removeEventListener("focusin", into);
      el.removeEventListener("focusout", away);
      if (within) refocus(trigger);
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      if (!inside(e.target as Node)) close.current();
    };
    // Caught first (window, capture), so a page's own Escape – e.g. closing a detail view – doesn't fire as well
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      // A menu or another popover opened from inside this one closes first
      const layer = (e.target as Element | null)?.closest?.("[popover]");
      if (layer && layer !== panel.current && panel.current?.contains(layer)) return;
      e.preventDefault();
      e.stopPropagation();
      const back = inside(document.activeElement);
      const trigger = triggerOf(anchorEl(), panel.current);
      close.current();
      if (back) trigger?.focus({ preventScroll: true });
    };
    // Tabbing out of the trigger and the popover closes it
    const out = (e: FocusEvent) => {
      const to = e.relatedTarget as Node | null;
      if (inside(e.target as Node) && to && !inside(to)) close.current();
    };
    document.addEventListener("pointerdown", down, true);
    window.addEventListener("keydown", key, true);
    document.addEventListener("focusout", out);
    return () => {
      document.removeEventListener("pointerdown", down, true);
      window.removeEventListener("keydown", key, true);
      document.removeEventListener("focusout", out);
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;
  const hasHead = shows(title) || shows(description);
  return (
    <div
      {...rest}
      ref={(el) => {
        panel.current = el;
        if (typeof ref === "function") ref(el);
        else if (ref) ref.current = el;
      }}
      className={["ui-pop", className].filter(Boolean).join(" ")}
      data-unstyled={unstyled || undefined}
      role={role}
      aria-labelledby={shows(title) ? titleId : rest["aria-labelledby"]}
      aria-describedby={shows(description) ? descId : rest["aria-describedby"]}
      tabIndex={-1}
      popover="manual"
      data-side={side}
      data-align={align}
      style={width != null ? { ...style, width, maxWidth: "calc(100vw - 16px)" } : style}
    >
      {/* React 19 hoists this into <head> once, no matter how many popovers render */}
      <style href="ui-popover" precedence="default">
        {css}
      </style>
      {hasHead && (
        <div className="ui-pop__head">
          {shows(title) && (
            <p className="ui-pop__title" id={titleId}>
              {title}
            </p>
          )}
          {shows(description) && (
            <p className="ui-pop__desc" id={descId}>
              {description}
            </p>
          )}
        </div>
      )}
      {children}
    </div>
  );
}

/* ---------- Helpers ---------- */

/** Text or an element – not true, false, null or an empty string */
const shows = (v: ReactNode) => v != null && typeof v !== "boolean" && v !== "";

/** The first control inside that is shown and reachable by Tab */
const firstControl = (root: Element) =>
  [...root.querySelectorAll<HTMLElement>("input, textarea, select, button, [href], [tabindex]")].find(
    (el) => el.tabIndex >= 0 && !(el as HTMLButtonElement).disabled && el.getClientRects().length > 0,
  );

/** The trigger: the anchor itself when it is a control, or its first control that isn't inside the popover */
function triggerOf(anchor: HTMLElement | null, panel: HTMLElement | null) {
  if (!anchor) return null;
  if (anchor.matches("button, [href], input, [tabindex]")) return anchor;
  for (const el of anchor.querySelectorAll<HTMLElement>("button, [href], input, [tabindex]")) if (!panel?.contains(el)) return el;
  return null;
}

/** Back to the trigger – unless something inside moved the focus somewhere on purpose */
const refocus = (trigger: HTMLElement | null) =>
  window.setTimeout(() => {
    const at = document.activeElement;
    if (trigger?.isConnected && (!at || at === document.body)) trigger.focus({ preventScroll: true });
  });

/** The top layer, so no overflow cuts it and no z-index fights it */
function showLayer(el: HTMLElement) {
  if ("showPopover" in el && !el.matches(":popover-open")) el.showPopover();
}
function hideLayer(el: HTMLElement) {
  if ("hidePopover" in el && el.isConnected && el.matches(":popover-open")) el.hidePopover();
}

/**
 * Puts the fixed card next to a rectangle: on the preferred side, or the other one when that has more room; the edge
 * it lines up with switches when it would stick out, and it is pushed inside the window as a last resort. Too tall
 * for the room it gets: it scrolls.
 */
function place(el: HTMLElement, r: DOMRect, side: "top" | "bottom" | "left" | "right", align: "start" | "center" | "end", gap: number) {
  const pad = 8;
  const vw = document.documentElement.clientWidth || window.innerWidth;
  const vh = window.innerHeight;
  el.style.maxHeight = "";
  const w = el.offsetWidth;
  const h = el.offsetHeight;
  const room = { bottom: vh - r.bottom - gap - pad, top: r.top - gap - pad, right: vw - r.right - gap - pad, left: r.left - gap - pad };
  const flip = { top: "bottom", bottom: "top", left: "right", right: "left" } as const;
  let s: keyof typeof room = side;
  let a = align;
  if (room[s] < (s === "top" || s === "bottom" ? h : w) && room[flip[s]] > room[s]) s = flip[s];
  // Beside it but no room either way (a phone): under it instead
  if ((s === "left" || s === "right") && room[s] < w) s = room.bottom >= room.top ? "bottom" : "top";
  let top: number;
  let left: number;
  if (s === "top" || s === "bottom") {
    const fit = Math.min(h, Math.max(120, room[s]));
    top = s === "bottom" ? r.bottom + gap : r.top - gap - fit;
    left = a === "start" ? r.left : a === "end" ? r.right - w : r.left + r.width / 2 - w / 2;
    if (a === "start" && left + w > vw - pad && r.right - w >= pad) (a = "end"), (left = r.right - w);
    else if (a === "end" && left < pad && r.left + w <= vw - pad) (a = "start"), (left = r.left);
    left = Math.min(Math.max(pad, left), vw - pad - w);
    if (h > fit) el.style.maxHeight = `${fit}px`;
  } else {
    left = s === "right" ? r.right + gap : r.left - gap - w;
    top = a === "start" ? r.top : a === "end" ? r.bottom - h : r.top + r.height / 2 - h / 2;
    if (a === "start" && top + h > vh - pad && r.bottom - h >= pad) (a = "end"), (top = r.bottom - h);
    else if (a === "end" && top < pad && r.top + h <= vh - pad) (a = "start"), (top = r.top);
    top = Math.min(Math.max(pad, top), Math.max(pad, vh - pad - h));
    if (h > vh - 2 * pad) el.style.maxHeight = `${vh - 2 * pad}px`;
  }
  el.style.top = `${Math.round(top)}px`;
  el.style.left = `${Math.round(left)}px`;
  el.dataset.side = s;
  el.dataset.align = a;
}

/* ---------- Styles ---------- */

const css = /* css */ `
/* Colors and motion as variables – override them on .ui-pop (see Theming in the docs) */
.ui-pop {
  --ui-pop-surface: var(--aui-overlay, var(--aui-surface, #ffffff));
  --ui-pop-strong: var(--aui-ink, #171717);
  --ui-pop-ink: var(--aui-ink, #171717);
  --ui-pop-muted: var(--aui-muted, #8f8f8f);
  --ui-pop-shadow: var(--aui-shadow-popover, 0 0 0 1px rgba(0, 0, 0, 0.06), 0 18px 40px -12px rgba(0, 0, 0, 0.18), 0 4px 12px -4px rgba(0, 0, 0, 0.06));
  --ui-pop-ease: var(--aui-ease, cubic-bezier(0.22, 1, 0.36, 1));

  /* A white card in the top layer: a 1px edge and a deeper drop */
  position: fixed;
  inset: auto;
  z-index: 1000;
  display: block;
  box-sizing: border-box;
  max-height: calc(100vh - 16px);
  margin: 0;
  border: 0;
  transform-origin: top left;
  animation: ui-pop-in 220ms var(--ui-pop-ease) both;
  max-width: calc(100vw - 16px);
}
/* Unstyled: the browser's popover look switched off at no weight, so any class of yours wins */
:where(.ui-pop) { padding: 0; background: none; color: inherit; overflow: visible; }
/* The card itself – left out with unstyled, so your own classes draw it */
.ui-pop:not([data-unstyled]) {
  /* Fits its content up to 360px – a long URL or name wraps instead of stretching it; the width prop lifts the cap */
  max-width: min(360px, calc(100vw - 16px));
  padding: 16px;
  border-radius: calc(var(--aui-radius-lg, 10px) + 6px);
  background: var(--ui-pop-surface);
  box-shadow: var(--ui-pop-shadow);
  color: var(--ui-pop-ink);
  font-family: var(--aui-font, "Inter", "InterVariable", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif);
  font-size: 13.5px;
  line-height: 20px;
  font-weight: 400;
  text-align: start;
  overflow: auto;
  overscroll-behavior: contain;
  -webkit-font-smoothing: antialiased;
}
.ui-pop::backdrop { display: none; }
.ui-pop:focus { outline: none; }
.ui-pop *, .ui-pop *::before, .ui-pop *::after { box-sizing: border-box; }

/* It grows out of the side and edge it is attached to */
.ui-pop[data-align="end"] { transform-origin: top right; }
.ui-pop[data-align="center"] { transform-origin: top center; }
.ui-pop[data-side="top"] { transform-origin: bottom left; animation-name: ui-pop-in-up; }
.ui-pop[data-side="top"][data-align="end"] { transform-origin: bottom right; }
.ui-pop[data-side="top"][data-align="center"] { transform-origin: bottom center; }
.ui-pop[data-side="right"] { transform-origin: top left; animation-name: ui-pop-in-right; }
.ui-pop[data-side="right"][data-align="end"] { transform-origin: bottom left; }
.ui-pop[data-side="right"][data-align="center"] { transform-origin: center left; }
.ui-pop[data-side="left"] { transform-origin: top right; animation-name: ui-pop-in-left; }
.ui-pop[data-side="left"][data-align="end"] { transform-origin: bottom right; }
.ui-pop[data-side="left"][data-align="center"] { transform-origin: center right; }

.ui-pop__head { display: grid; gap: 2px; min-width: 0; }
.ui-pop__head:not(:last-child) { margin-bottom: 14px; }
.ui-pop__title { margin: 0; font-weight: 500; color: var(--ui-pop-strong); overflow-wrap: anywhere; }
.ui-pop__desc { margin: 0; font-size: 12.5px; line-height: 17px; color: var(--ui-pop-muted); overflow-wrap: anywhere; }

@keyframes ui-pop-in { from { opacity: 0; transform: scale(0.96) translateY(-4px); } }
@keyframes ui-pop-in-up { from { opacity: 0; transform: scale(0.96) translateY(4px); } }
@keyframes ui-pop-in-right { from { opacity: 0; transform: scale(0.96) translateX(-4px); } }
@keyframes ui-pop-in-left { from { opacity: 0; transform: scale(0.96) translateX(4px); } }

/* Touch screens: 15px text, so it reads like the rest of a phone UI */
@media (pointer: coarse) {
  .ui-pop { padding: 16px; font-size: 15px; line-height: 22px; }
  .ui-pop__desc { font-size: 13px; line-height: 18px; }
}

@media (prefers-reduced-motion: reduce) {
  .ui-pop { animation-duration: 1ms; }
}

/* Dark mode: follows a .dark class or data-theme="dark" on any ancestor, e.g. <html> */
:where(.dark, [data-theme="dark"]) .ui-pop {
  --ui-pop-surface: var(--aui-overlay, var(--aui-surface, #19191b));
  --ui-pop-strong: var(--aui-ink, #ededed);
  --ui-pop-ink: var(--aui-ink, #ededed);
  --ui-pop-muted: var(--aui-muted, #8b8b92);
  --ui-pop-shadow: var(--aui-shadow-popover, 0 0 0 1px rgba(255, 255, 255, 0.06), 0 18px 40px -12px rgba(0, 0, 0, 0.6));
  color-scheme: dark;
}
`;
