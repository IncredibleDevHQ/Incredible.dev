// Adapted from affectUI's Progress Tracker (https://www.affectui.com), a free item under the MIT
// licence (licenses/affectui-MIT.txt). Changed for the house: it follows work as it happens rather
// than a checklist someone ticks (the steps before the current one are done, the current one turns,
// a step that stopped says so), and app.css gives it the house's colours through `--aui-*`.
import type { ReactNode } from "react";

export type ProgressStep = {
  id: string;
  label: string;
  /** Small icon on the right */
  icon?: ReactNode;
};

export type ProgressTrackerProps = {
  title?: string;
  steps: ProgressStep[];
  /** The step under way: the ones before it are done; "done" once all are; none before it starts */
  current?: string | null;
  /** The step under way stopped */
  failed?: boolean;
  className?: string;
};

export function ProgressTracker({ title = "Progress", steps, current = null, failed = false, className }: ProgressTrackerProps) {
  const total = steps.length;
  const at = current === "done" ? total : steps.findIndex((s) => s.id === current);
  const count = Math.max(0, at);
  return (
    <div className={["ui-progress", className].filter(Boolean).join(" ")} data-complete={count === total || undefined} data-failed={failed || undefined}>
      {/* React 19 hoists this into <head> once, no matter how many trackers render */}
      <style href="ui-progress-tracker" precedence="default">
        {css}
      </style>

      <div className="ui-progress__head">
        <h3 className="ui-progress__title" dir="auto" title={title}>
          {title}
        </h3>
        <span className="ui-progress__count" aria-hidden="true">
          <span className="ui-progress__digit" key={count}>
            {num.format(count)}
          </span>
          /{num.format(total)}
        </span>
      </div>

      <div
        className="ui-progress__bar"
        role="progressbar"
        aria-label={title}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={count}
        aria-valuetext={`${num.format(count)} of ${num.format(total)} done`}
      >
        <span className="ui-progress__fill" style={{ transform: `scaleX(${total ? count / total : 0})` }}>
          {/* A new key replays the shine each time progress grows */}
          <span className="ui-progress__shine" key={count} />
        </span>
      </div>

      <ol className="ui-progress__list">
        {steps.map((step, index) => {
          const state = index < count ? "done" : index === at ? (failed ? "failed" : "current") : "waiting";
          return (
            <li key={step.id} className="ui-progress__step" data-state={state} aria-current={state === "current" ? "step" : undefined} style={{ animationDelay: `${180 + Math.min(index, 12) * 90}ms` }}>
              <span className="ui-progress__check" aria-hidden="true">
                <svg viewBox="0 0 24 24">{state === "failed" ? <path d="M12 7v6M12 16.5v.5" pathLength={1} /> : <path d="M6.5 12.5l3.5 3.5 7.5-8" pathLength={1} />}</svg>
              </span>
              <span className="ui-progress__label" title={step.label || undefined}>
                <span dir="auto">{step.label || " "}</span>
              </span>
              {step.icon && (
                <span className="ui-progress__icon" aria-hidden="true">
                  {step.icon}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// 1284 → "1,284"
const num = new Intl.NumberFormat("en");

/* ---------- Styles ---------- */

const css = /* css */ `
/* Colors and motion as variables – override them on .ui-progress, or set the --aui-* theme */
.ui-progress {
  --ui-pg-card: var(--aui-surface, #ffffff);
  --ui-pg-line: var(--aui-border, #e5e5e5);
  --ui-pg-ink: var(--aui-ink, #171717);
  --ui-pg-muted: var(--aui-muted, #a3a3a3);
  --ui-pg-ring: var(--aui-border-strong, #8f8f8f);
  --ui-pg-track: #f0f0f0;
  --ui-pg-done: var(--aui-success, #171717);
  --ui-pg-danger: var(--aui-danger, #c4320a);
  --ui-pg-ease: cubic-bezier(0.22, 1, 0.36, 1);

  box-sizing: border-box;
  width: 100%;
  padding: 22px 16px 14px;
  background: var(--ui-pg-card);
  border: 1px solid var(--ui-pg-line);
  border-radius: 20px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03), 0 8px 24px rgba(0, 0, 0, 0.035);
  font-family: var(--aui-font, "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif);
  color: var(--ui-pg-ink);
  -webkit-font-smoothing: antialiased;
  animation: ui-progress-in 520ms var(--ui-pg-ease) both;
}
.ui-progress *, .ui-progress *::before, .ui-progress *::after { box-sizing: border-box; }

.ui-progress__head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 0 6px; }
.ui-progress__title { margin: 0; min-width: 0; overflow-wrap: anywhere; font-size: 16px; font-weight: 550; letter-spacing: -0.01em; }
.ui-progress__count { font-size: 14px; color: var(--ui-pg-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
/* The number rolls in from below whenever it changes */
.ui-progress__digit { display: inline-block; animation: ui-progress-roll 560ms var(--ui-pg-ease); }

.ui-progress__bar { position: relative; height: 8px; margin: 16px 6px 12px; border-radius: 999px; background: var(--ui-pg-track); overflow: hidden; }
.ui-progress__fill { position: absolute; inset: 0; border-radius: inherit; background: var(--ui-pg-done); transform-origin: 0 50%; overflow: hidden; transition: transform 1100ms var(--ui-pg-ease); }
.ui-progress[data-failed] .ui-progress__fill { background: var(--ui-pg-danger); }
.ui-progress__shine { position: absolute; inset: 0; background: linear-gradient(90deg, transparent 30%, rgba(255, 255, 255, 0.28) 50%, transparent 70%) 0 0 / 220% 100% no-repeat; animation: ui-progress-shine 1400ms ease-out both; }

.ui-progress__list { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px; margin: 0; padding: 0; list-style: none; }
.ui-progress__step { display: flex; align-items: center; gap: 12px; padding: 9px 6px; border-radius: 12px; font-size: 15px; line-height: 1.45; animation: ui-progress-row-in 640ms var(--ui-pg-ease) both; }

/* The ring: waiting, turning while its step runs, filled with a tick that draws itself once done */
.ui-progress__check { position: relative; flex: none; display: grid; place-items: center; width: 20px; height: 20px; border: 1.5px solid var(--ui-pg-ring); border-radius: 50%; transition: background-color 220ms var(--ui-pg-ease), border-color 220ms var(--ui-pg-ease); }
.ui-progress__check svg { width: 14px; height: 14px; fill: none; stroke: #ffffff; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 1; stroke-dashoffset: 1; }
.ui-progress__step[data-state="done"] .ui-progress__check { background: var(--ui-pg-done); border-color: var(--ui-pg-done); animation: ui-progress-pop 560ms var(--ui-pg-ease); }
.ui-progress__step[data-state="done"] .ui-progress__check svg { stroke-dashoffset: 0; transition: stroke-dashoffset 420ms var(--ui-pg-ease) 160ms; }
.ui-progress__step[data-state="current"] .ui-progress__check { border-color: var(--ui-pg-line); border-top-color: var(--ui-pg-done); animation: ui-progress-turn 800ms linear infinite; }
.ui-progress__step[data-state="failed"] .ui-progress__check { background: var(--ui-pg-danger); border-color: var(--ui-pg-danger); }
.ui-progress__step[data-state="failed"] .ui-progress__check svg { stroke-dashoffset: 0; }

.ui-progress__label { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transition: color 300ms ease; }
.ui-progress__step[data-state="waiting"] .ui-progress__label { color: var(--ui-pg-muted); }
.ui-progress__step[data-state="current"] .ui-progress__label { font-weight: 550; }
.ui-progress__step[data-state="failed"] .ui-progress__label { color: var(--ui-pg-danger); font-weight: 550; }

.ui-progress__icon { flex: none; display: grid; place-items: center; width: 18px; height: 18px; overflow: hidden; }
.ui-progress__icon > :is(svg, img) { width: 100%; height: 100%; object-fit: contain; }

@keyframes ui-progress-pop { 0% { transform: scale(0.9); } 60% { transform: scale(1.06); } 100% { transform: scale(1); } }
@keyframes ui-progress-turn { to { transform: rotate(360deg); } }
@keyframes ui-progress-in { from { opacity: 0; transform: translateY(8px); } }
@keyframes ui-progress-row-in { from { opacity: 0; filter: blur(3px); transform: translateY(8px); } }
@keyframes ui-progress-roll { from { opacity: 0; transform: translateY(60%); } to { opacity: 1; transform: none; } }
@keyframes ui-progress-shine { from { background-position: 120% 0; opacity: 1; } to { background-position: -20% 0; opacity: 0; } }

@media (prefers-reduced-motion: reduce) {
  .ui-progress, .ui-progress *, .ui-progress *::before, .ui-progress *::after { animation: none !important; transition-duration: 1ms !important; transition-delay: 0ms !important; }
}

/* Dark mode: follows a .dark class or data-theme="dark" on any ancestor, e.g. <html> */
:where(.dark, [data-theme="dark"]) .ui-progress {
  --ui-pg-card: var(--aui-surface, #232326);
  --ui-pg-line: var(--aui-border, rgba(255, 255, 255, 0.08));
  --ui-pg-ink: var(--aui-ink, #ededed);
  --ui-pg-muted: var(--aui-muted, #8f8f8f);
  --ui-pg-ring: var(--aui-border-strong, #6b6b70);
  --ui-pg-track: rgba(255, 255, 255, 0.1);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 8px 24px rgba(0, 0, 0, 0.35);
}
`;
