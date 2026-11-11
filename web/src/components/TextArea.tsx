// affectUI's Text Area (https://www.affectui.com), a free item under the MIT licence
// (licenses/affectui-MIT.txt), as it comes; app.css gives it the house's colours through `--aui-*`.
import { useEffect, useId, useLayoutEffect, useRef, useState, type ComponentPropsWithRef, type ReactNode } from "react";

/*
 * Text Area – a single self-contained file.
 * The multi-line twin of the Text Field: a label, a hint the error takes the place of, a character count, a box that
 * grows with the text between minRows and maxRows (then scrolls), an optional button that gives it more room and
 * ⌘/Ctrl+Enter to send. A white field with a soft gray edge; focus only darkens the edge – no ring.
 * The styles are injected below, so no extra files are needed.
 */

export type TextAreaProps = Omit<ComponentPropsWithRef<"textarea">, "rows"> & {
  /** Shown above the field and tied to it */
  label?: ReactNode;
  /** A quiet line under the field – the error takes its place while there is one */
  hint?: ReactNode;
  /** Marks the field invalid and shows this under it, in place of the hint */
  error?: ReactNode;
  /** "Optional" next to the label */
  optional?: boolean;
  /** Shows "120/2000" under the field; needs maxLength */
  counter?: boolean;
  /** Height when empty, in lines */
  minRows?: number;
  /** It grows with the text up to this many lines, then scrolls */
  maxRows?: number;
  /** A small button in the corner that gives the field more room (expandedRows) and back */
  expandable?: boolean;
  /** Lines while expanded */
  expandedRows?: number;
  /** Controls the expanded state from outside */
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  /** ⌘/Ctrl+Enter – e.g. save or send without leaving the keyboard */
  onSubmitShortcut?: (value: string) => void;
  /** Extra class on the textarea itself; className goes on the wrapper */
  inputClassName?: string;
};

export function TextArea({
  label,
  hint,
  error,
  optional = false,
  counter = false,
  minRows = 3,
  maxRows = 10,
  expandable = false,
  expandedRows = 16,
  expanded: expandedProp,
  onExpandedChange,
  onSubmitShortcut,
  className,
  inputClassName,
  id,
  value,
  defaultValue,
  onChange,
  onKeyDown,
  disabled,
  readOnly,
  maxLength,
  ref,
  "aria-describedby": describedBy,
  ...rest
}: TextAreaProps) {
  const autoId = useId();
  const inputId = id ?? `${autoId}-input`;
  const messageId = `${autoId}-message`;
  const counterId = `${autoId}-count`;
  const area = useRef<HTMLTextAreaElement | null>(null);

  // The current text, for the count and the height – follows value when controlled, the field itself otherwise
  const [own, setOwn] = useState(String(defaultValue ?? ""));
  const text = value !== undefined && value !== null ? String(value) : own;

  const [ownExpanded, setOwnExpanded] = useState(false);
  const expanded = expandable && (expandedProp ?? ownExpanded);
  // The height glides only when the room changes on purpose – never while typing
  const [gliding, setGliding] = useState(false);
  const glideTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(glideTimer.current), []);

  const invalid = Boolean(error) || rest["aria-invalid"] === true || rest["aria-invalid"] === "true";
  const message = shows(error) ? error : shows(hint) ? hint : null;
  const showCount = counter && typeof maxLength === "number";
  const fallbackName =
    label == null && !rest["aria-label"] && !rest["aria-labelledby"] && typeof rest.placeholder === "string" ? rest.placeholder : undefined;

  // Fits the height to the text: at least minRows (expandedRows while expanded), at most maxRows, then it scrolls
  const fit = () => {
    const el = area.current;
    if (!el) return;
    const cs = getComputedStyle(el);
    const line = parseFloat(cs.lineHeight) || 20;
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const min = (expanded ? Math.max(expandedRows, minRows) : minRows) * line + pad;
    const max = (expanded ? Math.max(expandedRows, maxRows) : Math.max(maxRows, minRows)) * line + pad;
    const before = el.style.height;
    el.style.height = "auto";
    const needed = el.scrollHeight;
    const next = Math.min(Math.max(needed, min), max);
    // Back to the old height and a read, so a glide starts from there and not from "auto"
    el.style.height = before;
    void el.offsetHeight;
    el.style.height = `${next}px`;
    el.style.overflowY = needed > max + 1 ? "auto" : "hidden";
  };

  useLayoutEffect(fit, [text, expanded, minRows, maxRows, expandedRows]); // eslint-disable-line react-hooks/exhaustive-deps

  // A narrower or wider field wraps differently – measure again
  useEffect(() => {
    const el = area.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let width = el.clientWidth;
    const ro = new ResizeObserver(() => {
      if (el.clientWidth === width) return;
      width = el.clientWidth;
      fit();
    });
    // A new text size (a touch screen, a zoom) changes the line height too
    const mq = window.matchMedia("(pointer: coarse)");
    mq.addEventListener("change", fit);
    ro.observe(el);
    return () => {
      ro.disconnect();
      mq.removeEventListener("change", fit);
    };
  }); // eslint-disable-line react-hooks/exhaustive-deps

  // An uncontrolled field follows form.reset(), so the count and the height don't keep the old text
  useEffect(() => {
    const form = area.current?.form;
    if (!form || value !== undefined) return;
    const onReset = () => window.setTimeout(() => setOwn(area.current?.value ?? ""));
    form.addEventListener("reset", onReset);
    return () => form.removeEventListener("reset", onReset);
  }, [value]);

  const toggle = () => {
    const next = !expanded;
    setGliding(true);
    window.clearTimeout(glideTimer.current);
    glideTimer.current = window.setTimeout(() => setGliding(false), 320);
    if (expandedProp === undefined) setOwnExpanded(next);
    onExpandedChange?.(next);
  };

  return (
    <div
      className={["ui-ta", className].filter(Boolean).join(" ")}
      data-invalid={invalid || undefined}
      data-disabled={disabled || undefined}
      data-readonly={readOnly || undefined}
      data-expandable={expandable || undefined}
    >
      {/* React 19 hoists this into <head> once, no matter how many fields render */}
      <style href="ui-text-area" precedence="default">
        {css}
      </style>
      {label != null && (
        <div className="ui-ta__head">
          <label className="ui-ta__label" htmlFor={inputId}>
            {label}
          </label>
          {optional && <span className="ui-ta__optional">Optional</span>}
        </div>
      )}
      <div className="ui-ta__box">
        <textarea
          {...rest}
          ref={(el) => {
            area.current = el;
            if (typeof ref === "function") ref(el);
            else if (ref) ref.current = el;
          }}
          id={inputId}
          className={["ui-ta__input", inputClassName].filter(Boolean).join(" ")}
          rows={minRows}
          value={value}
          defaultValue={defaultValue}
          disabled={disabled}
          readOnly={readOnly}
          maxLength={maxLength}
          dir={rest.dir ?? "auto"}
          aria-label={rest["aria-label"] ?? fallbackName}
          aria-invalid={invalid || undefined}
          aria-describedby={[describedBy, message ? messageId : null, showCount ? counterId : null].filter(Boolean).join(" ") || undefined}
          aria-keyshortcuts={onSubmitShortcut ? "Meta+Enter Control+Enter" : rest["aria-keyshortcuts"]}
          data-gliding={gliding || undefined}
          onChange={(e) => {
            if (value === undefined) setOwn(e.target.value);
            onChange?.(e);
          }}
          onKeyDown={(e) => {
            if (onSubmitShortcut && e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing) {
              e.preventDefault();
              onSubmitShortcut(e.currentTarget.value);
            }
            onKeyDown?.(e);
          }}
        />
        {expandable && !disabled && (
          <button
            type="button"
            className="ui-ta__expand"
            aria-label={expanded ? "Less room" : "More room"}
            aria-pressed={expanded}
            aria-controls={inputId}
            onClick={toggle}
          >
            <span className="ui-ta__swap" key={expanded ? "less" : "more"}>
              {expanded ? <CollapseIcon /> : <ExpandIcon />}
            </span>
          </button>
        )}
      </div>
      {(message || showCount) && (
        <div className="ui-ta__foot">
          {/* The error swaps in where the hint was, so the form below doesn't move */}
          <p className="ui-ta__message" id={messageId} key={shows(error) ? "error" : "hint"} dir="auto" aria-live={shows(error) ? "polite" : undefined}>
            {message}
          </p>
          {showCount && (
            <span
              className="ui-ta__count"
              id={counterId}
              data-full={text.length === maxLength || undefined}
              data-over={text.length > maxLength || undefined}
            >
              {text.length.toLocaleString()}/{maxLength.toLocaleString()}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** Text or an element – not true, false, null or an empty string */
const shows = (v: ReactNode) => v != null && typeof v !== "boolean" && v !== "";

/* Icons: Hugeicons Free (MIT), drawn at 16px */
function ExpandIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M16.5 3h4.5v4.5M21 3l-6 6M7.5 21H3v-4.5M3 21l6-6" />
    </svg>
  );
}
function CollapseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14.5 5v4.5H19M14.5 9.5 20 4M9.5 19v-4.5H5M9.5 14.5 4 20" />
    </svg>
  );
}

const css = /* css */ `
/* Colors and motion as variables – override them on .ui-ta (see Theming in the docs) */
.ui-ta {
  --ui-ta-title: var(--aui-ink, #171717);
  --ui-ta-ink: var(--aui-ink, #171717);
  --ui-ta-muted: var(--aui-muted, #8f8f8f);
  --ui-ta-subtle: var(--aui-muted, #8f8f8f);
  --ui-ta-faint: var(--aui-placeholder, #b5b5b5);
  --ui-ta-icon: var(--aui-muted, #8f8f8f);
  --ui-ta-text: #404040;
  --ui-ta-surface: var(--aui-surface, #ffffff);
  --ui-ta-line: var(--aui-border, #e6e6e8);
  --ui-ta-edge: var(--aui-border-strong, #d4d4d8);
  --ui-ta-edge-focus: var(--aui-border-strong, #b4b4bb);
  --ui-ta-wash: #f4f4f5;
  --ui-ta-readonly: #fafafa;
  --ui-ta-danger: var(--aui-danger, #c4320a);
  --ui-ta-danger-edge: #ff8a7a;
  --ui-ta-danger-edge-focus: #f04438;
  --ui-ta-danger-wash: color-mix(in srgb, var(--aui-red, #f04438) 4%, transparent);
  --ui-ta-focus: var(--aui-focus, rgba(0, 96, 226, 0.7));
  --ui-ta-ease: cubic-bezier(0.22, 1, 0.36, 1);

  --fs: 13.5px;
  --lh: 21px;

  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
  font-family: var(--aui-font, "Inter", "InterVariable", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif);
  font-size: 13.5px;
  line-height: 20px;
  color: var(--ui-ta-ink);
  -webkit-font-smoothing: antialiased;
}
/* Touch screens: 16px text, so iOS doesn't zoom in on focus */
@media (pointer: coarse) {
  .ui-ta { --fs: 16px; --lh: 24px; }
}

.ui-ta__head { display: flex; align-items: baseline; gap: 6px; min-width: 0; padding: 0 2px; }
.ui-ta__label { min-width: 0; font-size: 13px; font-weight: 500; color: var(--ui-ta-title); overflow-wrap: anywhere; cursor: default; }
.ui-ta__optional { flex: none; font-size: 12px; line-height: 16px; color: var(--ui-ta-subtle); }

/* The box: white with a 1px gray edge; hover and focus only darken that edge */
.ui-ta__box {
  position: relative;
  display: flex;
  min-width: 0;
  border-radius: var(--aui-radius, 10px);
  background: var(--ui-ta-surface);
  box-shadow: 0 0 0 1px var(--ui-ta-line), 0 1px 2px rgba(0, 0, 0, 0.04);
  cursor: text;
  transition: box-shadow 140ms ease, background-color 140ms ease;
}
.ui-ta__box:hover { box-shadow: 0 0 0 1px var(--ui-ta-edge), 0 1px 2px rgba(0, 0, 0, 0.04); }
.ui-ta__box:focus-within { box-shadow: 0 0 0 1px var(--ui-ta-edge-focus), 0 1px 2px rgba(0, 0, 0, 0.04); }
.ui-ta[data-invalid] .ui-ta__box { background: var(--ui-ta-danger-wash); box-shadow: 0 0 0 1px var(--ui-ta-danger-edge), 0 1px 2px rgba(0, 0, 0, 0.04); animation: ui-ta-nudge 320ms var(--ui-ta-ease); }
.ui-ta[data-invalid] .ui-ta__box:focus-within { box-shadow: 0 0 0 1px var(--ui-ta-danger-edge-focus), 0 1px 2px rgba(0, 0, 0, 0.04); }
.ui-ta[data-readonly] .ui-ta__box { background: var(--ui-ta-readonly); box-shadow: 0 0 0 1px var(--ui-ta-line); cursor: default; }
.ui-ta[data-disabled] .ui-ta__box { background: var(--ui-ta-readonly); box-shadow: 0 0 0 1px var(--ui-ta-line); cursor: not-allowed; }
.ui-ta[data-disabled] { opacity: 0.55; }

.ui-ta__input {
  display: block;
  flex: 1;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  margin: 0;
  padding: 8px 12px;
  border: 0;
  border-radius: inherit;
  outline: 0;
  background: transparent;
  font: inherit;
  font-size: var(--fs);
  line-height: var(--lh);
  color: var(--ui-ta-ink);
  overflow-wrap: anywhere;
  resize: none;
  overflow-y: hidden;
  scrollbar-width: thin;
  -webkit-appearance: none;
  appearance: none;
}
/* The corner button keeps clear of the text */
.ui-ta[data-expandable] .ui-ta__input { padding-inline-end: 36px; }
.ui-ta__input::placeholder { color: var(--ui-ta-faint); opacity: 1; }
.ui-ta__input:disabled { cursor: not-allowed; }
.ui-ta__input[data-gliding] { transition: height 300ms var(--ui-ta-ease); }

/* More room: a small ghost button in the top corner */
.ui-ta__expand {
  position: absolute;
  top: 4px;
  inset-inline-end: 4px;
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--ui-ta-icon);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: background-color 140ms ease, color 140ms ease;
}
.ui-ta__expand:hover { background: var(--ui-ta-wash); color: var(--ui-ta-ink); }
.ui-ta__expand:focus-visible { outline: 2px solid var(--ui-ta-focus); outline-offset: -2px; }
.ui-ta__expand svg { display: block; }
.ui-ta__swap { display: grid; animation: ui-ta-swap 280ms var(--ui-ta-ease); }
@media (pointer: coarse) {
  .ui-ta__expand { width: 32px; height: 32px; }
  .ui-ta__expand::before { content: ""; position: absolute; inset: -4px; }
  .ui-ta[data-expandable] .ui-ta__input { padding-inline-end: 42px; }
}

/* Under the field: the hint, or the error in its place, and the count */
.ui-ta__foot { display: flex; align-items: flex-start; gap: 12px; min-width: 0; padding: 0 2px; }
.ui-ta__message {
  flex: 1;
  min-width: 0;
  margin: 0;
  font-size: 12.5px;
  line-height: 17px;
  color: var(--ui-ta-subtle);
  overflow-wrap: anywhere;
  animation: ui-ta-message 260ms var(--ui-ta-ease);
}
.ui-ta[data-invalid] .ui-ta__message { color: var(--ui-ta-danger); }
.ui-ta__count { flex: none; margin-left: auto; font-size: 12px; line-height: 16px; font-variant-numeric: tabular-nums; color: var(--ui-ta-faint); transition: color 140ms ease; }
.ui-ta__count[data-full] { color: var(--ui-ta-text); }
.ui-ta__count[data-over] { color: var(--ui-ta-danger); }

@keyframes ui-ta-nudge {
  30% { transform: translateX(-3px); }
  65% { transform: translateX(2px); }
}
@keyframes ui-ta-message {
  from { opacity: 0; transform: translateY(-3px); filter: blur(2px); }
}
@keyframes ui-ta-swap {
  from { opacity: 0; transform: scale(0.6); filter: blur(2px); }
}

@media (prefers-reduced-motion: reduce) {
  .ui-ta *, .ui-ta[data-invalid] .ui-ta__box { animation-duration: 1ms !important; }
  .ui-ta__box, .ui-ta__input[data-gliding] { transition-duration: 1ms; }
}

/* Dark mode: follows a .dark class or data-theme="dark" on any ancestor, e.g. <html> */
:where(.dark, [data-theme="dark"]) .ui-ta {
  --ui-ta-title: var(--aui-ink, #ededed);
  --ui-ta-ink: var(--aui-ink, #ededed);
  --ui-ta-text: #c8c8cc;
  --ui-ta-muted: var(--aui-muted, #8b8b92);
  --ui-ta-subtle: var(--aui-muted, #8b8b92);
  --ui-ta-faint: var(--aui-placeholder, #5c5c63);
  --ui-ta-icon: var(--aui-muted, #8b8b92);
  --ui-ta-surface: var(--aui-surface, #19191b);
  --ui-ta-line: var(--aui-border, #2a2a2e);
  --ui-ta-edge: var(--aui-border-strong, #3a3a40);
  --ui-ta-edge-focus: var(--aui-border-strong, #4e4e55);
  --ui-ta-wash: #26262a;
  --ui-ta-readonly: #151517;
  --ui-ta-danger: var(--aui-danger, #ff8a7a);
  --ui-ta-danger-edge: color-mix(in srgb, var(--aui-red, #ff6b5f) 45%, transparent);
  --ui-ta-danger-edge-focus: rgba(255, 99, 105, 0.75);
  --ui-ta-danger-wash: color-mix(in srgb, var(--aui-red, #ff6b5f) 6%, transparent);
  --ui-ta-focus: var(--aui-focus, rgba(77, 141, 255, 0.8));
}
`;
