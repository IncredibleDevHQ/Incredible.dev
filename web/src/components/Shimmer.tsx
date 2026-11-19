// affectUI's Shimmer Loader (https://www.affectui.com), a free item under the MIT licence
// (licenses/affectui-MIT.txt), as it comes; app.css gives it the house's colours through `--aui-*`.
import type { CSSProperties, ReactNode } from "react";

/*
 * Shimmer Loader – loading states with a soft light sweep, in a single self-contained file.
 * Skeleton draws placeholder blocks; the highlight is pinned to the viewport (background-attachment: fixed),
 * so every skeleton on the page shares one sweep that travels across them together. ShimmerText runs a
 * highlight band through the letters of a label, like an AI "Thinking…" state. The styles are injected below.
 */

export type SkeletonProps = {
  /** Width – a number is px, a string any CSS length; defaults to 100% */
  width?: number | string;
  /** Height – a number is px, a string any CSS length; defaults to 12px */
  height?: number | string;
  /** Corner radius; defaults to 6px */
  radius?: number | string;
  /** Round shape, e.g. for avatars – uses width for both sides */
  circle?: boolean;
  className?: string;
  style?: CSSProperties;
};

export type ShimmerTextProps = {
  children: ReactNode;
  /** Seconds for one pass of the highlight */
  duration?: number;
  className?: string;
};

const len = (v: number | string | undefined) => (typeof v === "number" ? `${v}px` : v);

const Style = () => (
  <style href="ui-shimmer-loader" precedence="default">
    {css}
  </style>
);

export function Skeleton({ width, height, radius, circle, className, style }: SkeletonProps) {
  const w = len(width);
  return (
    <>
      <Style />
      <span
        className={["ui-shm", className].filter(Boolean).join(" ")}
        aria-hidden="true"
        style={{
          flexShrink: circle || typeof width === "number" ? 0 : undefined,
          width: w,
          height: circle ? (w ?? len(height)) : len(height),
          borderRadius: circle ? "50%" : len(radius),
          ...style,
        }}
      />
    </>
  );
}

export function ShimmerText({ children, duration = 2, className }: ShimmerTextProps) {
  return (
    <>
      <Style />
      <span
        className={["ui-shm-text", className].filter(Boolean).join(" ")}
        style={{ "--ui-shm-text-dur": `${duration}s` } as CSSProperties}
      >
        {children}
      </span>
    </>
  );
}

/* ---------- Styles ---------- */

const css = /* css */ `
.ui-shm,
.ui-shm-text {
  --ui-shm-base: #ececec;
  --ui-shm-glow: rgba(255, 255, 255, 0.9);
  --ui-shm-text: #a3a3a3;
  --ui-shm-text-glow: #ffffff;
  --ui-shm-dur: 2.2s;
}

/* Skeleton: one fixed gradient for the whole viewport, so all blocks sweep together */
.ui-shm {
  display: block;
  /* Fixed sizes keep their size in a row; a % width shrinks to the room that's left */
  flex: 0 1 auto;
  min-width: 0;
  width: 100%;
  height: 12px;
  max-width: 100%;
  border-radius: 6px;
  background-color: var(--ui-shm-base);
  background-image: linear-gradient(
    100deg,
    transparent 0%,
    transparent 30%,
    var(--ui-shm-glow) 50%,
    transparent 70%,
    transparent 100%
  );
  background-size: 150vw 100%;
  background-repeat: repeat-x;
  background-attachment: fixed;
  animation: ui-shm-sweep var(--ui-shm-dur) linear infinite;
}
@keyframes ui-shm-sweep {
  from { background-position: -50vw 0; }
  to { background-position: 100vw 0; }
}

/* Text: a highlight band runs through the letters */
.ui-shm-text {
  display: inline-block;
  color: var(--ui-shm-text);
  background-image: linear-gradient(
    90deg,
    var(--ui-shm-text) 0%,
    var(--ui-shm-text) 40%,
    var(--ui-shm-text-glow) 50%,
    var(--ui-shm-text) 60%,
    var(--ui-shm-text) 100%
  );
  background-size: 300% 100%;
  background-position: 100% 0;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: ui-shm-text var(--ui-shm-text-dur, 2s) linear infinite;
}
@keyframes ui-shm-text {
  from { background-position: 100% 0; }
  to { background-position: 0% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .ui-shm { animation: none; background-image: none; }
  .ui-shm-text { animation: none; background-image: none; -webkit-text-fill-color: currentColor; }
}

/* Dark mode: follows a .dark class or data-theme="dark" on any ancestor, e.g. <html> */
:where(.dark, [data-theme="dark"]) .ui-shm,
:where(.dark, [data-theme="dark"]) .ui-shm-text {
  --ui-shm-base: #2f2f33;
  --ui-shm-glow: rgba(255, 255, 255, 0.08);
  --ui-shm-text: #6e6e73;
  --ui-shm-text-glow: #f5f5f5;
}
`;
