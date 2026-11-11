// Adapted from affectUI's Select (https://www.affectui.com), a free item under the MIT
// licence (licenses/affectui-MIT.txt). Changed for the house: it can open on hover (`openOnHover`),
// and app.css gives it the house's colours through its `--aui-*` variables.
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent as HoverEvent, type ReactNode, type Ref } from "react";

/*
 * Select – a single self-contained file.
 * Pick one option from a list: a field in the Text Field's look that opens a list under it (or above, when there is
 * no room), options with an icon and a quiet second line, a check on the chosen one and a soft highlight that glides
 * to where the pointer or the arrow keys are. Typing a letter jumps to the option. The list sits in the top layer,
 * so a card's overflow never cuts it. The styles are injected below, so no extra files are needed.
 */

export type SelectOption = {
  value: string;
  label: string;
  /** A quiet second line under the label */
  description?: string;
  /** A 16px icon before the label, e.g. an inline SVG */
  icon?: ReactNode;
  disabled?: boolean;
};

export type SelectProps = {
  options: SelectOption[];
  /** The chosen value – makes it controlled */
  value?: string | null;
  defaultValue?: string | null;
  onChange?: (value: string, option: SelectOption) => void;
  /** Shown while nothing is chosen */
  placeholder?: string;
  /** Shown above the field and tied to it */
  label?: ReactNode;
  /** A quiet line under the field – the error takes its place while there is one */
  hint?: ReactNode;
  /** Marks the field invalid and shows this under it, in place of the hint */
  error?: ReactNode;
  /** "Optional" next to the label */
  optional?: boolean;
  /** sm 28 · md 32 · lg 36 high */
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  /** Sends the value with a form, through a hidden input */
  name?: string;
  required?: boolean;
  id?: string;
  className?: string;
  "aria-label"?: string;
  ref?: Ref<HTMLButtonElement>;
  /** Opens while a mouse rests on it, and closes a moment after it leaves; clicks and keys still work */
  openOnHover?: boolean;
};

export function Select({
  options,
  value: valueProp,
  defaultValue = null,
  onChange,
  placeholder = "Choose…",
  label,
  hint,
  error,
  optional = false,
  size = "md",
  disabled = false,
  name,
  required,
  id,
  className,
  "aria-label": ariaLabel,
  ref,
  openOnHover = false,
}: SelectProps) {
  const autoId = useId();
  const triggerId = id ?? `${autoId}-trigger`;
  const listId = `${autoId}-list`;
  const labelId = `${autoId}-label`;
  const messageId = `${autoId}-message`;
  const optionId = (i: number) => `${autoId}-option-${i}`;

  const [own, setOwn] = useState<string | null>(defaultValue);
  const value = valueProp !== undefined ? valueProp : own;
  const chosen = options.find((o) => o.value === value) ?? null;

  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [place, setPlace] = useState<{ top: number; left: number; width: number; maxHeight: number; up: boolean } | null>(null);
  const [glow, setGlow] = useState<{ top: number; height: number } | null>(null);

  const trigger = useRef<HTMLButtonElement | null>(null);
  const list = useRef<HTMLDivElement | null>(null);
  const typed = useRef({ text: "", at: 0 });
  // Hover: a short wait before it opens or closes, so passing over it or crossing to the list is
  // forgiven; a click just after a hover opened it keeps it open.
  const linger = useRef<number | undefined>(undefined);
  const hovered = useRef(0);

  const invalid = Boolean(error);
  const message = shows(error) ? error : shows(hint) ? hint : null;
  const scale = SIZES.includes(size) ? size : "md";
  const enabled = (i: number) => i >= 0 && i < options.length && !options[i].disabled;

  const first = () => options.findIndex((o) => !o.disabled);
  const last = () => {
    for (let i = options.length - 1; i >= 0; i--) if (!options[i].disabled) return i;
    return -1;
  };
  const step = (from: number, dir: 1 | -1) => {
    for (let i = from + dir; i >= 0 && i < options.length; i += dir) if (!options[i].disabled) return i;
    return from;
  };

  const show = (at?: number) => {
    if (disabled || !options.length) return;
    const chosenAt = options.findIndex((o) => o.value === value);
    setActive(at ?? (enabled(chosenAt) ? chosenAt : first()));
    setOpen(true);
  };
  const hide = (focusBack = true) => {
    setOpen(false);
    setGlow(null);
    setPlace(null);
    if (focusBack) trigger.current?.focus({ preventScroll: true });
  };
  const pick = (i: number) => {
    if (!enabled(i)) return;
    const o = options[i];
    if (valueProp === undefined) setOwn(o.value);
    if (o.value !== value) onChange?.(o.value, o);
    hide();
  };

  // Where the list goes: under the field, or above it when there is more room there; as wide as the field
  const measure = () => {
    const t = trigger.current;
    if (!t) return;
    const r = t.getBoundingClientRect();
    const gap = 4;
    const edge = 8;
    const below = window.innerHeight - r.bottom - gap - edge;
    const above = r.top - gap - edge;
    const want = Math.min(list.current?.scrollHeight ?? 280, 288);
    const up = below < Math.min(want, 160) && above > below;
    const width = Math.max(r.width, 180);
    const left = Math.min(Math.max(edge, r.left), window.innerWidth - width - edge);
    setPlace({ top: up ? r.top - gap : r.bottom + gap, left, width, maxHeight: Math.max(120, Math.min(288, up ? above : below)), up });
  };

  useLayoutEffect(() => {
    if (!open) return;
    const el = list.current;
    // The top layer, so no overflow cuts it and no z-index fights it
    if (el && "showPopover" in el && !el.matches(":popover-open")) el.showPopover();
    measure();
    const update = () => measure();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      if (el && "hidePopover" in el && el.matches(":popover-open")) el.hidePopover();
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // A press anywhere else closes it, without taking the focus back
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      const target = e.target as Node;
      if (trigger.current?.contains(target) || list.current?.contains(target)) return;
      hide(false);
    };
    document.addEventListener("pointerdown", down, true);
    return () => document.removeEventListener("pointerdown", down, true);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // The highlight glides to the active option, and the list scrolls it into view
  useLayoutEffect(() => {
    if (!open || active < 0) return;
    const row = list.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    if (!row) return;
    setGlow({ top: row.offsetTop, height: row.offsetHeight });
    row.scrollIntoView({ block: "nearest" });
  }, [active, open, place]);

  // Typing letters jumps to the next option that starts with them, like a native select
  const typeahead = (key: string) => {
    const now = Date.now();
    typed.current.text = now - typed.current.at > 700 ? key : typed.current.text + key;
    typed.current.at = now;
    const q = typed.current.text.toLowerCase();
    const start = open ? active : options.findIndex((o) => o.value === value);
    const order = [...options.keys()].map((k) => (k + start + (q.length === 1 ? 1 : 0) + options.length) % options.length);
    const hit = order.find((i) => enabled(i) && options[i].label.toLowerCase().startsWith(q));
    if (hit === undefined) return;
    if (open) setActive(hit);
    else pick(hit);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        show();
      } else if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) typeahead(e.key);
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActive((a) => step(a, 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActive((a) => step(a, -1));
        break;
      case "Home":
      case "PageUp":
        e.preventDefault();
        setActive(first());
        break;
      case "End":
      case "PageDown":
        e.preventDefault();
        setActive(last());
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        if (e.key === " " && Date.now() - typed.current.at < 700) typeahead(" ");
        else pick(active);
        break;
      case "Escape":
        e.preventDefault();
        hide();
        break;
      case "Tab":
        hide(false);
        break;
      default:
        if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) typeahead(e.key);
    }
  };

  useEffect(() => () => window.clearTimeout(linger.current), []);
  const enter = (e: HoverEvent) => {
    if (!openOnHover || e.pointerType !== "mouse") return;
    window.clearTimeout(linger.current);
    if (!open)
      linger.current = window.setTimeout(() => {
        hovered.current = Date.now();
        show();
      }, 120);
  };
  const leave = (e: HoverEvent) => {
    if (!openOnHover || e.pointerType !== "mouse") return;
    window.clearTimeout(linger.current);
    linger.current = window.setTimeout(() => hide(false), 260);
  };

  return (
    <div
      className={["ui-sel", className].filter(Boolean).join(" ")}
      data-size={scale}
      data-open={open || undefined}
      data-invalid={invalid || undefined}
      data-disabled={disabled || undefined}
      onPointerEnter={enter}
      onPointerLeave={leave}
    >
      {/* React 19 hoists this into <head> once, no matter how many selects render */}
      <style href="ui-select" precedence="default">
        {css}
      </style>
      {label != null && (
        <div className="ui-sel__head">
          <label className="ui-sel__label" id={labelId} htmlFor={triggerId}>
            {label}
          </label>
          {optional && <span className="ui-sel__optional">Optional</span>}
        </div>
      )}
      <button
        ref={(el) => {
          trigger.current = el;
          if (typeof ref === "function") ref(el);
          else if (ref) ref.current = el;
        }}
        id={triggerId}
        type="button"
        className="ui-sel__trigger"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabel ? undefined : label != null ? `${labelId} ${triggerId}` : undefined}
        aria-describedby={message ? messageId : undefined}
        aria-invalid={invalid || undefined}
        aria-required={required || undefined}
        disabled={disabled}
        onClick={() => {
          if (open && Date.now() - hovered.current < 800) return;
          if (open) hide();
          else show();
        }}
        onKeyDown={onKeyDown}
      >
        {chosen?.icon && (
          <span className="ui-sel__icon" aria-hidden="true">
            {chosen.icon}
          </span>
        )}
        <span className="ui-sel__value" data-empty={chosen ? undefined : ""} title={chosen?.label}>
          {chosen ? chosen.label : placeholder}
        </span>
        <span className="ui-sel__chevron" aria-hidden="true">
          <ChevronIcon />
        </span>
      </button>
      {name && <input type="hidden" name={name} value={value ?? ""} />}
      {open && (
        <div
          ref={list}
          id={listId}
          className="ui-sel__list"
          role="listbox"
          aria-labelledby={label != null ? labelId : undefined}
          aria-label={label == null ? ariaLabel ?? placeholder : undefined}
          popover="manual"
          data-up={place?.up || undefined}
          style={place ? { top: place.up ? undefined : place.top, bottom: place.up ? window.innerHeight - place.top : undefined, left: place.left, width: place.width, maxHeight: place.maxHeight } : undefined}
          onPointerLeave={() => setActive(-1)}
        >
          {glow && <span className="ui-sel__glow" aria-hidden="true" style={{ transform: `translateY(${glow.top}px)`, height: glow.height }} />}
          {options.map((o, i) => (
            <div
              key={o.value}
              id={optionId(i)}
              className="ui-sel__option"
              role="option"
              data-index={i}
              aria-selected={o.value === value}
              aria-disabled={o.disabled || undefined}
              data-active={i === active || undefined}
              onPointerMove={() => o.disabled || i === active || setActive(i)}
              onPointerDown={(e) => e.preventDefault()}
              onClick={() => pick(i)}
            >
              {o.icon && (
                <span className="ui-sel__icon" aria-hidden="true">
                  {o.icon}
                </span>
              )}
              <span className="ui-sel__text">
                <span className="ui-sel__option-label">{o.label}</span>
                {o.description && <span className="ui-sel__option-hint">{o.description}</span>}
              </span>
              <span className="ui-sel__check" aria-hidden="true">
                {o.value === value && <CheckIcon />}
              </span>
            </div>
          ))}
        </div>
      )}
      {message && (
        <p className="ui-sel__message" id={messageId} key={shows(error) ? "error" : "hint"} aria-live={shows(error) ? "polite" : undefined}>
          {message}
        </p>
      )}
    </div>
  );
}

const SIZES = ["sm", "md", "lg"];
/** Text or an element – not true, false, null or an empty string */
const shows = (v: ReactNode) => v != null && typeof v !== "boolean" && v !== "";

/* Icons: Hugeicons Free (MIT) */
function ChevronIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m7 10 5 5 5-5" />
    </svg>
  );
}
function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path className="ui-sel__tick" d="M5 12.5 9.5 17 19 7" pathLength={1} />
    </svg>
  );
}

const css = /* css */ `
/* Colors and motion as variables – override them on .ui-sel (see Theming in the docs) */
.ui-sel {
  --ui-sel-title: var(--aui-ink, #171717);
  --ui-sel-ink: var(--aui-ink, #171717);
  --ui-sel-subtle: var(--aui-muted, #8f8f8f);
  --ui-sel-faint: var(--aui-placeholder, #b5b5b5);
  --ui-sel-icon: var(--aui-muted, #8f8f8f);
  --ui-sel-surface: var(--aui-surface, #ffffff);
  --ui-sel-menu: var(--aui-surface, #ffffff);
  --ui-sel-line: var(--aui-border, #e6e6e8);
  --ui-sel-edge: var(--aui-border-strong, #d4d4d8);
  --ui-sel-edge-open: var(--aui-border-strong, #b4b4bb);
  --ui-sel-glow: #f4f4f5;
  --ui-sel-readonly: #fafafa;
  --ui-sel-shadow-menu: 0 0 0 1px rgba(0, 0, 0, 0.06), 0 18px 40px -12px rgba(0, 0, 0, 0.18), 0 4px 12px -4px rgba(0, 0, 0, 0.06);
  --ui-sel-danger: var(--aui-danger, #c4320a);
  --ui-sel-danger-edge: #ff8a7a;
  --ui-sel-danger-wash: rgba(240, 68, 56, 0.04);
  --ui-sel-focus: var(--aui-focus, rgba(0, 96, 226, 0.7));
  --ui-sel-ease: cubic-bezier(0.22, 1, 0.36, 1);

  --h: 36px;
  --px: 12px;
  --fs: 13.5px;
  --radius: var(--aui-radius, 10px);

  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
  font-family: var(--aui-font, "Inter", "InterVariable", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif);
  font-size: 13.5px;
  line-height: 20px;
  color: var(--ui-sel-ink);
  -webkit-font-smoothing: antialiased;
}
.ui-sel[data-size="sm"] { --h: 32px; --px: 10px; --fs: 13px; --radius: calc(var(--aui-radius, 10px) - 1px); }
.ui-sel[data-size="lg"] { --h: 40px; --px: 14px; --fs: 14px; --radius: calc(var(--aui-radius, 10px) + 2px); }
/* Touch screens: a comfortable tap height and 16px text */
@media (pointer: coarse) {
  .ui-sel { --fs: 16px; }
  .ui-sel[data-size="sm"] { --h: 36px; }
  .ui-sel[data-size="md"] { --h: 40px; }
  .ui-sel[data-size="lg"] { --h: 44px; }
}

.ui-sel__head { display: flex; align-items: baseline; gap: 6px; min-width: 0; padding: 0 2px; }
.ui-sel__label { min-width: 0; font-size: 13px; font-weight: 500; color: var(--ui-sel-title); overflow-wrap: anywhere; cursor: default; }
.ui-sel__optional { flex: none; font-size: 12px; line-height: 16px; color: var(--ui-sel-subtle); }

/* The field: the Text Field's look – white with a 1px gray edge that darkens on hover and while open */
.ui-sel__trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  box-sizing: border-box;
  width: 100%;
  height: var(--h);
  min-width: 0;
  margin: 0;
  padding: 0 calc(var(--px) - 2px) 0 var(--px);
  border: 0;
  border-radius: var(--radius);
  background: var(--ui-sel-surface);
  box-shadow: 0 0 0 1px var(--ui-sel-line), 0 1px 2px rgba(0, 0, 0, 0.04);
  font: inherit;
  font-size: var(--fs);
  color: var(--ui-sel-ink);
  text-align: start;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: box-shadow 140ms ease, background-color 140ms ease;
}
.ui-sel__trigger:hover { box-shadow: 0 0 0 1px var(--ui-sel-edge), 0 1px 2px rgba(0, 0, 0, 0.04); }
.ui-sel[data-open] .ui-sel__trigger { box-shadow: 0 0 0 1px var(--ui-sel-edge-open), 0 1px 2px rgba(0, 0, 0, 0.04); }
.ui-sel__trigger:focus-visible { outline: 2px solid var(--ui-sel-focus); outline-offset: 2px; }
.ui-sel[data-invalid] .ui-sel__trigger { background: var(--ui-sel-danger-wash); box-shadow: 0 0 0 1px var(--ui-sel-danger-edge), 0 1px 2px rgba(0, 0, 0, 0.04); }
.ui-sel__trigger:disabled { background: var(--ui-sel-readonly); box-shadow: 0 0 0 1px var(--ui-sel-line); cursor: not-allowed; }
.ui-sel[data-disabled] { opacity: 0.55; }

.ui-sel__value { flex: 1; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.ui-sel__value[data-empty] { color: var(--ui-sel-faint); }
.ui-sel__icon { display: grid; flex: none; place-items: center; width: 16px; height: 16px; color: var(--ui-sel-icon); }
.ui-sel__icon > svg, .ui-sel__icon > img { display: block; width: 16px; height: 16px; }
.ui-sel__chevron { display: grid; flex: none; place-items: center; width: 16px; height: 16px; color: var(--ui-sel-icon); transition: transform 240ms var(--ui-sel-ease); }
.ui-sel[data-open] .ui-sel__chevron { transform: rotate(180deg); }

/* The list: a white card in the top layer, at the field's edge */
.ui-sel__list {
  position: fixed;
  inset: auto;
  z-index: 1000;
  box-sizing: border-box;
  margin: 0;
  padding: 5px;
  border: 0;
  border-radius: 14px;
  background: var(--ui-sel-menu);
  box-shadow: var(--ui-sel-shadow-menu);
  color: var(--ui-sel-ink);
  font: inherit;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  transform-origin: top center;
  animation: ui-sel-in 200ms var(--ui-sel-ease) both;
}
.ui-sel__list[data-up] { transform-origin: bottom center; }
.ui-sel__list::backdrop { display: none; }

/* One soft highlight that glides between the rows */
.ui-sel__glow {
  position: absolute;
  top: 0;
  left: 5px;
  right: 5px;
  border-radius: 9px;
  background: var(--ui-sel-glow);
  pointer-events: none;
  transition: transform 180ms var(--ui-sel-ease), height 180ms var(--ui-sel-ease);
}

.ui-sel__option {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 7px 10px;
  box-sizing: border-box;
  border-radius: 9px;
  font-size: 13.5px;
  line-height: 20px;
  cursor: pointer;
  user-select: none;
}
.ui-sel__option[aria-disabled] { color: var(--ui-sel-faint); cursor: default; }
.ui-sel__option[aria-disabled] .ui-sel__icon { opacity: 0.5; }
.ui-sel__text { display: grid; flex: 1; min-width: 0; }
.ui-sel__option-label { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.ui-sel__option[aria-selected="true"] .ui-sel__option-label { font-weight: 500; }
.ui-sel__option-hint { overflow: hidden; font-size: 12px; line-height: 16px; white-space: nowrap; text-overflow: ellipsis; color: var(--ui-sel-subtle); }
.ui-sel__check { display: grid; flex: none; place-items: center; width: 16px; height: 16px; color: var(--ui-sel-ink); }
.ui-sel__tick { stroke-dasharray: 1; animation: ui-sel-draw 280ms 40ms var(--ui-sel-ease) both; }
@media (pointer: coarse) {
  .ui-sel__option { min-height: 40px; font-size: 15px; }
}

.ui-sel__message { margin: 0; padding: 0 2px; font-size: 12.5px; line-height: 17px; color: var(--ui-sel-subtle); overflow-wrap: anywhere; animation: ui-sel-message 260ms var(--ui-sel-ease); }
.ui-sel[data-invalid] .ui-sel__message { color: var(--ui-sel-danger); }

@keyframes ui-sel-in {
  from { opacity: 0; transform: translateY(-4px) scale(0.98); }
}
.ui-sel__list[data-up] { animation-name: ui-sel-in-up; }
@keyframes ui-sel-in-up {
  from { opacity: 0; transform: translateY(4px) scale(0.98); }
}
@keyframes ui-sel-draw {
  from { stroke-dashoffset: 1; }
  to { stroke-dashoffset: 0; }
}
@keyframes ui-sel-message {
  from { opacity: 0; transform: translateY(-3px); filter: blur(2px); }
}

@media (prefers-reduced-motion: reduce) {
  .ui-sel *, .ui-sel__list { animation-duration: 1ms !important; }
  .ui-sel__glow, .ui-sel__chevron, .ui-sel__trigger { transition-duration: 1ms; }
}

/* Dark mode: follows a .dark class or data-theme="dark" on any ancestor, e.g. <html> */
:where(.dark, [data-theme="dark"]) .ui-sel {
  --ui-sel-title: var(--aui-ink, #ededed);
  --ui-sel-ink: var(--aui-ink, #ededed);
  --ui-sel-subtle: var(--aui-muted, #8b8b92);
  --ui-sel-faint: var(--aui-placeholder, #5c5c63);
  --ui-sel-icon: var(--aui-muted, #8b8b92);
  --ui-sel-surface: var(--aui-surface, #19191b);
  --ui-sel-menu: var(--aui-surface, #19191b);
  --ui-sel-line: var(--aui-border, #2a2a2e);
  --ui-sel-edge: var(--aui-border-strong, #3a3a40);
  --ui-sel-edge-open: var(--aui-border-strong, #4e4e55);
  --ui-sel-glow: #26262a;
  --ui-sel-readonly: #151517;
  --ui-sel-shadow-menu: 0 0 0 1px rgba(255, 255, 255, 0.06), 0 18px 40px -12px rgba(0, 0, 0, 0.6);
  --ui-sel-danger: var(--aui-danger, #ff8a7a);
  --ui-sel-danger-edge: rgba(255, 107, 95, 0.45);
  --ui-sel-danger-wash: rgba(255, 107, 95, 0.06);
  --ui-sel-focus: var(--aui-focus, rgba(77, 141, 255, 0.8));
}
`;
