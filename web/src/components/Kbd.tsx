// affectUI's Kbd (https://www.affectui.com), a free item under the MIT licence
// (licenses/affectui-MIT.txt), as it comes; app.css gives it the house's colours through `--aui-*`.
import { useSyncExternalStore, type ComponentPropsWithRef } from "react";

/*
 * Kbd – a single self-contained file.
 * A key chip for shortcuts in menus, tooltips and help lists: one key (Esc), or a combo in one chip (⌘K). The key
 * `mod` is ⌘ on a Mac and Ctrl everywhere else; screen readers hear the keys spelled out ("Command K").
 * The styles are injected below, so no extra files are needed.
 */

export type KbdPlatform = "mac" | "other";

export type KbdProps = ComponentPropsWithRef<"kbd"> & {
  /**
   * One key or a combo, e.g. "esc" or ["mod", "K"]. Named keys: mod, cmd, ctrl, alt (option), shift, enter, esc, tab,
   * space, backspace, delete, up, down, left, right, pageup, pagedown, home, end – anything else is shown as it is.
   * Leave it out to show the children as one plain key.
   */
  keys?: string | readonly string[];
  /** sm: 18px high, 11px text – in menus and hints · md: 22px high, 12px text – in lists and help */
  size?: "sm" | "md";
  /** Draw the keys for a Mac (⌘ ⌥ ⇧) or for Windows and Linux (Ctrl, Alt, Shift) – found out on its own when left out */
  platform?: KbdPlatform;
};

export function Kbd({ keys, size = "sm", platform, className, children, ...rest }: KbdProps) {
  const detected = usePlatform();
  const os = platform === "mac" || platform === "other" ? platform : detected;
  const list = keys == null ? [] : (typeof keys === "string" ? [keys] : [...keys]).filter((k) => typeof k === "string" && k.trim() !== "");
  const parts = list.map((k) => describe(k, os));
  // Nothing to show – no keys, no children: no empty chip either
  if (!parts.length && (children == null || children === false || children === "")) return null;

  return (
    <>
      {/* React 19 hoists this into <head> once, no matter how many chips render */}
      <style href="ui-kbd" precedence="default">
        {css}
      </style>
      <kbd
        className={["ui-kbd", className].filter(Boolean).join(" ")}
        data-size={size === "md" ? "md" : "sm"}
        data-os={os}
        {...rest}
      >
        {parts.length ? (
          <>
            {/* The glyphs are for the eye; the spelled-out names for screen readers ("Command Shift P") */}
            <span className="ui-kbd__keys" aria-hidden="true">
              {parts.map((p, i) => (
                <span key={i} className="ui-kbd__key" data-glyph={p.glyph ? "" : undefined}>
                  {p.label}
                </span>
              ))}
            </span>
            <span className="ui-kbd__sr">{parts.map((p) => p.spoken).join(" ")}</span>
          </>
        ) : (
          children
        )}
      </kbd>
    </>
  );
}

/* ---------- Keys ---------- */

type Named = { mac: string; other: string; spoken: [mac: string, other: string]; glyph?: boolean };

const NAMED: Record<string, Named> = {
  mod: { mac: "⌘", other: "Ctrl", spoken: ["Command", "Control"], glyph: true },
  cmd: { mac: "⌘", other: "⌘", spoken: ["Command", "Command"], glyph: true },
  ctrl: { mac: "⌃", other: "Ctrl", spoken: ["Control", "Control"], glyph: true },
  alt: { mac: "⌥", other: "Alt", spoken: ["Option", "Alt"], glyph: true },
  shift: { mac: "⇧", other: "Shift", spoken: ["Shift", "Shift"], glyph: true },
  enter: { mac: "↵", other: "Enter", spoken: ["Return", "Enter"], glyph: true },
  esc: { mac: "Esc", other: "Esc", spoken: ["Escape", "Escape"] },
  tab: { mac: "Tab", other: "Tab", spoken: ["Tab", "Tab"] },
  space: { mac: "Space", other: "Space", spoken: ["Space", "Space"] },
  backspace: { mac: "⌫", other: "Backspace", spoken: ["Delete", "Backspace"], glyph: true },
  delete: { mac: "⌦", other: "Del", spoken: ["Forward delete", "Delete"], glyph: true },
  up: { mac: "↑", other: "↑", spoken: ["Up arrow", "Up arrow"], glyph: true },
  down: { mac: "↓", other: "↓", spoken: ["Down arrow", "Down arrow"], glyph: true },
  left: { mac: "←", other: "←", spoken: ["Left arrow", "Left arrow"], glyph: true },
  right: { mac: "→", other: "→", spoken: ["Right arrow", "Right arrow"], glyph: true },
  pageup: { mac: "PgUp", other: "PgUp", spoken: ["Page up", "Page up"] },
  pagedown: { mac: "PgDn", other: "PgDn", spoken: ["Page down", "Page down"] },
  home: { mac: "Home", other: "Home", spoken: ["Home", "Home"] },
  end: { mac: "End", other: "End", spoken: ["End", "End"] },
};

/** Other spellings people use for the same key */
const ALIAS: Record<string, string> = {
  command: "cmd", meta: "cmd", "⌘": "cmd", control: "ctrl", option: "alt", opt: "alt", return: "enter", escape: "esc",
  del: "delete", arrowup: "up", arrowdown: "down", arrowleft: "left", arrowright: "right", pgup: "pageup", pgdn: "pagedown",
};

/** Spoken names for punctuation a screen reader might skip */
const SPOKEN: Record<string, string> = {
  ".": "Period", ",": "Comma", "/": "Slash", "\\": "Backslash", "?": "Question mark", "[": "Left bracket",
  "]": "Right bracket", "-": "Minus", "+": "Plus", "=": "Equals", ";": "Semicolon", "'": "Quote", "`": "Backtick",
};

const describe = (raw: string, os: KbdPlatform) => {
  const key = raw.trim();
  const id = ALIAS[key.toLowerCase()] ?? key.toLowerCase();
  const named = NAMED[id];
  if (named) {
    const mac = os === "mac";
    const label = mac ? named.mac : named.other;
    return { label, spoken: named.spoken[mac ? 0 : 1], glyph: !!named.glyph && label.length === 1 };
  }
  // A single letter reads as a capital, like on the key itself
  const label = key.length === 1 ? key.toUpperCase() : key;
  return { label, spoken: SPOKEN[key] ?? label, glyph: false };
};

/* ---------- Platform ---------- */

const noop = () => () => {};
const isMac = () => {
  if (typeof navigator === "undefined") return false;
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
  return /mac|iphone|ipad|ipod/i.test(nav.userAgentData?.platform || nav.platform || nav.userAgent || "");
};
/** "other" on the server and during hydration, then the real platform – no hydration mismatch */
const usePlatform = (): KbdPlatform => (useSyncExternalStore(noop, isMac, () => false) ? "mac" : "other");

/* ---------- Styles ---------- */

const css = /* css */ `
/* Colors as variables – override them on .ui-kbd (see Theming in the docs). A small white keycap with a 1px edge and a
   slightly heavier bottom, like a key on the keyboard */
.ui-kbd {
  --ui-kbd-bg: var(--aui-surface, #ffffff);
  --ui-kbd-ink: var(--aui-muted, #616161);
  --ui-kbd-line: var(--aui-border, #e3e3e3);
  --ui-kbd-depth: #d9d9d9;
  --h: 18px;
  --pad: 5px;

  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  min-width: var(--h);
  height: var(--h);
  margin: 0;
  padding: 0 var(--pad);
  border-radius: calc(var(--aui-radius-sm, 7px) - 2px);
  background: var(--ui-kbd-bg);
  box-shadow: inset 0 0 0 1px var(--ui-kbd-line), inset 0 -1px 0 var(--ui-kbd-depth);
  color: var(--ui-kbd-ink);
  font-family: var(--aui-font, "Inter", "InterVariable", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif);
  font-size: 11px;
  font-weight: 500;
  font-style: normal;
  line-height: 1;
  letter-spacing: 0.02em;
  white-space: nowrap;
  vertical-align: middle;
  font-variant-numeric: tabular-nums;
  -webkit-font-smoothing: antialiased;
  user-select: none;
}
.ui-kbd[data-size="md"] {
  --h: 22px;
  --pad: 6px;
  border-radius: calc(var(--aui-radius-sm, 7px) - 1px);
  font-size: 12px;
}

/* A combo sits in one chip: ⌘K close together, "Ctrl K" with a small space – left to right even in RTL text, like
   the keys are pressed */
.ui-kbd__keys {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  direction: ltr;
  unicode-bidi: isolate;
  /* The heavier bottom edge takes a pixel – the glyphs sit a half pixel higher to look centred */
  translate: 0 -0.5px;
}
.ui-kbd[data-os="other"] .ui-kbd__keys { gap: 3px; }
/* ⌘ ⇧ ⌥ and arrows look small next to letters in most fonts – a touch larger */
.ui-kbd__key[data-glyph] { font-size: 1.1em; }

/* Read by screen readers, not drawn */
.ui-kbd__sr {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
.ui-kbd:has(.ui-kbd__sr) { position: relative; }

/* Windows high contrast: the shadows are dropped, an edge keeps the chip visible */
@media (forced-colors: active) {
  .ui-kbd { border: 1px solid CanvasText; }
}

/* Dark mode: follows a .dark class or data-theme="dark" on any ancestor, e.g. <html> */
:where(.dark, [data-theme="dark"]) .ui-kbd {
  --ui-kbd-bg: var(--aui-surface, #232326);
  --ui-kbd-ink: var(--aui-muted, #a1a1a6);
  --ui-kbd-line: var(--aui-border, #34343a);
  --ui-kbd-depth: #1a1a1d;
}
`;
