// The plan being written, across the whole screen. Written for this house from notes on how
// agent-progress components behave; no other component's source is in it.
//
// - The head: who writes it, the film's name, the stage it is on and how long it has run, Stop.
//   Under it, every turn the writer took as one strip of time, each as wide as it ran, the house's
//   checks between turns as quieter gaps, and the turn under way growing at the end.
// - The plan: its stages on the house's agent trail, each with its own time, a finished one with
//   what it left behind, and the one at work with the writer's steps and words under it as they
//   come, and a line when it has said nothing for a while.
// - Turns: each turn as a line with its own first words and how long it took. The list stays at
//   its newest line unless a person scrolls up to read, and then offers the way back down.
// - So far: the film's idea once it is found, its chapters as they land, and what it is made from.
import { Check, RotateCcw, Square, X } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type EpisodeLength, type EpisodeRun, type EpisodeView, type WriterId } from "../../api";
import { LEVEL_NAMES, mmss, voiceName } from "../../episode";
import { useHouse } from "../../store";
import { AgentMark } from "../../ui";
import { Tooltip } from "../Tooltip";
import { Elapsed, type Run } from "./Ask";
import { WRITERS } from "./Film";
import { AgentTrail, type TrailStage, type TrailState } from "../agent/AgentTrail";

// A pause between two turns shorter than this is the house handing over, not checking: no gap.
const GAP = 2;

// What a stage that has not started will do, in a few words.
const AHEAD: Record<string, string> = {
  brief: "Finds the one idea in your material",
  script: "Writes the chapters and their beats",
  frames: "Gives every line its frame and picture",
  check: "Checks the length, the pace and the pictures",
};

// Long paths keep their head and, mostly, their tail: the file's own name is what is read.
const middle = (text: string, most: number) => (text.length <= most ? text : `${text.slice(0, Math.ceil(most * 0.35))}…${text.slice(-Math.floor(most * 0.6))}`);

// A writer's answer, in plain words: no markdown marks, its list items run on with a dot, one run
// of text.
const plain = (text: string) =>
  text
    .replace(/[*_`#>]+/g, "")
    .replace(/(^|\n|\s)[-•]\s+/g, "$1· ")
    .replace(/\s+/g, " ")
    .replace(/(:|^)\s*·\s*/g, "$1 ")
    .trim();

const lasted = (seconds: number) => {
  const whole = Math.max(0, Math.round(seconds));
  if (whole < 60) return `${whole}s`;
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
};

const lengthName = (seconds: EpisodeLength) => (seconds === "auto" ? "Decided by the material" : `${mmss(seconds[0])} to ${mmss(seconds[1])}`);

// Where the plan stands: the index of the stage under way, or every stage when it is written.
function stageAt(view: EpisodeView): number {
  const name = view.stage.name === "redo" || view.stage.name === "fix" ? "frames" : (view.stage.name ?? "brief");
  if (name === "done") return view.steps.length;
  return Math.max(
    0,
    view.steps.findIndex((s) => s.id === name),
  );
}

// The time now, once a second, while something on the page still runs.
function useNow(live: boolean): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!live) return;
    setNow(Date.now() / 1000);
    const tick = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(tick);
  }, [live]);
  return now;
}

export function PlanRun({ view, run, busy }: { view: EpisodeView; run: Run; busy: boolean }) {
  const failed = view.status === "failed";
  const writer = WRITERS[view.writer] ?? "the writer";
  const turns = useMemo(() => view.runs.filter((r) => r.lane === "plan").sort((a, b) => a.started_at - b.started_at), [view.runs]);
  const at = stageAt(view);
  const now = useNow(!failed);
  const began = turns[0]?.started_at ?? view.stage.at ?? now;
  const ended = failed ? (turns.at(-1)?.ended_at ?? now) : now;
  // How long what happens now has run: the turn under way, or the house's check since the last
  // turn ended. (A stage's own start is not kept, so the stage is not timed as a whole.)
  const live = turns.find((t) => t.state === "working");
  const since = live?.started_at ?? turns.at(-1)?.ended_at ?? view.stage.at;
  // A turn pointed at on the strip or in the log: the other lights up with it.
  const [lit, setLit] = useState<string | null>(null);
  return (
    <main className="ep-run" aria-label={failed ? "The plan stopped" : `Planning with ${writer}`}>
      <header className="ep-run-head">
        <AgentMark mark={view.writer} />
        <div className="ep-run-name">
          <p className="ep-kicker">{failed ? "The plan stopped" : `Planning with ${writer}`}</p>
          <h1 title={view.title}>{view.title}</h1>
        </div>
        <p className="ep-run-clock">
          <span>{failed ? `Stopped at stage ${Math.min(at + 1, view.steps.length)} of ${view.steps.length}` : `Stage ${Math.min(at + 1, view.steps.length)} of ${view.steps.length}`}</span>
          <time aria-label={`${lasted(ended - began)} so far`}>{mmss(ended - began)}</time>
        </p>
        {!failed && (
          <button type="button" className="btn" onClick={() => void api.stopEpisode(view.id).catch((e: Error) => useHouse.getState().say(e.message))}>
            <Square />
            Stop
          </button>
        )}
      </header>
      <TimeStrip turns={turns} now={now} failed={failed} lit={lit} onLight={setLit} />
      <div className="ep-run-body">
        <PlanTrail view={view} at={at} since={since} turns={turns} />
        <NowLog view={view} turns={turns} lit={lit} onLight={setLit} run={run} busy={busy} />
        <SoFar view={view} />
      </div>
    </main>
  );
}

type Span = { kind: "turn"; run: EpisodeRun; n: number; from: number; to: number } | { kind: "gap"; from: number; to: number; live: boolean };

function TimeStrip({ turns, now, failed, lit, onLight }: { turns: EpisodeRun[]; now: number; failed: boolean; lit: string | null; onLight: (id: string | null) => void }) {
  if (!turns.length) return <div className="ep-run-strip" data-empty aria-hidden="true" />;
  const spans: Span[] = [];
  turns.forEach((t, i) => {
    const before = i ? (turns[i - 1].ended_at ?? t.started_at) : t.started_at;
    if (t.started_at - before >= GAP) spans.push({ kind: "gap", from: before, to: t.started_at, live: false });
    spans.push({ kind: "turn", run: t, n: i + 1, from: t.started_at, to: t.ended_at ?? now });
  });
  // after the last turn, while the house reads what it wrote and the next one starts
  const last = turns[turns.length - 1];
  if (!failed && last.ended_at && now - last.ended_at >= GAP) spans.push({ kind: "gap", from: last.ended_at, to: now, live: true });
  const total = Math.max(1, spans[spans.length - 1].to - spans[0].from);
  return (
    <ol className="ep-run-strip" aria-label={`${turns.length} ${turns.length === 1 ? "turn" : "turns"} so far`} data-lighting={lit ? true : undefined}>
      {spans.map((s) =>
        s.kind === "gap" ? (
          <li key={`gap-${s.from}`} className="ep-run-gap" data-live={s.live || undefined} style={{ flexGrow: (s.to - s.from) / total }} aria-hidden="true" />
        ) : (
          <li key={s.run.id} data-state={s.run.state} data-lit={lit === s.run.id || undefined} style={{ flexGrow: (s.to - s.from) / total }}>
            <Tooltip content={`Turn ${s.n} · ${s.run.state === "working" ? "now" : lasted(s.to - s.from)}${s.run.said ? ` · ${middle(plain(s.run.said), 90)}` : ""}`} side="bottom">
              <button
                type="button"
                aria-label={`Turn ${s.n}, ${s.run.state === "working" ? "under way" : `${lasted(s.to - s.from)}, ${s.run.state}`}`}
                onPointerEnter={() => onLight(s.run.id)}
                onPointerLeave={() => onLight(null)}
                onFocus={() => onLight(s.run.id)}
                onBlur={() => onLight(null)}
                onClick={() =>
                  document.getElementById(`ep-turn-${s.run.id}`)?.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" })
                }
              />
            </Tooltip>
          </li>
        ),
      )}
    </ol>
  );
}

// The plan as the house's agent trail: each stage with its own time, the one at work saying who
// is at it, with the writer's steps and words under it as they come, and a finished one saying
// what it left behind. A plan written before the house dated its stages says where it stands.
function PlanTrail({ view, at, since, turns }: { view: EpisodeView; at: number; since?: number; turns: EpisodeRun[] }) {
  const failed = view.status === "failed";
  const stage = view.stage;
  const live = turns.find((t) => t.state === "working");
  // between the writer's turns the house reads what was written, or readies the next turn
  const between = stage.state === "reading" ? "Checking" : (stage.round ?? 0) > 0 ? `Fixing · round ${stage.round}` : "Getting ready";
  const kept = new Map(view.plan_stages.map((s) => [s.id, s]));
  const done = Math.min(at, view.steps.length);
  const steps: TrailStage[] = view.steps.map((s, i) => {
    const got = kept.get(s.id);
    const state: TrailState = got ? got.state : i < at ? "done" : i === at ? (failed ? "failed" : "running") : "pending";
    return {
      id: s.id,
      label: s.label,
      state,
      startedAt: got?.started_at ?? (state === "running" ? since : null),
      endedAt: got?.ended_at ?? null,
      doing: state === "running" ? (live ? "Writing" : between) : undefined,
      working: state === "running" && Boolean(live),
      word: state === "failed" ? "Stopped" : undefined,
      detail: state === "done" ? outcome(s.id, view) : state === "pending" ? AHEAD[s.id] : undefined,
    };
  });
  return (
    <section className="ep-run-panel ep-run-plan" aria-labelledby="ep-run-plan-title">
      <header className="ep-run-panel-head">
        <h2 id="ep-run-plan-title">The plan</h2>
        <span className="ep-run-count" aria-hidden="true">
          {done}/{view.steps.length}
        </span>
      </header>
      <AgentTrail label="The plan, stage by stage" steps={steps} events={live ? (view.working?.events ?? []) : []} turnSince={live?.started_at ?? null} />
    </section>
  );
}

// What a finished stage left behind, in a few words.
function outcome(id: string, view: EpisodeView): string {
  const w = view.written;
  if (id === "brief") return w.material ? `${w.material} passages read` : "Read";
  if (id === "script") {
    const beats = w.chapters.reduce((n, c) => n + c.beats, 0);
    return w.chapters.length ? `${w.chapters.length} chapters · ${beats} beats` : "Written";
  }
  if (id === "frames") return "Every line framed";
  return "Checked";
}

function NowLog({ view, turns, lit, onLight, run, busy }: { view: EpisodeView; turns: EpisodeRun[]; lit: string | null; onLight: (id: string | null) => void; run: Run; busy: boolean }) {
  const failed = view.status === "failed";
  const scroller = useRef<HTMLDivElement>(null);
  // The list keeps to its newest turn while a person reads there; scrolled up, it stays put.
  const [pinned, setPinned] = useState(true);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && pinned) el.scrollTop = el.scrollHeight;
  }, [turns.length, pinned, failed]);
  const onScroll = () => {
    const el = scroller.current;
    if (el) setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };
  const toLatest = () => {
    const el = scroller.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    setPinned(true);
  };
  return (
    <section className="ep-run-panel ep-run-now" aria-labelledby="ep-run-now-title">
      <header className="ep-run-panel-head">
        <h2 id="ep-run-now-title">{failed ? "Where it stopped" : "Turns"}</h2>
      </header>
      <div className="ep-run-scroll" ref={scroller} onScroll={onScroll}>
        <ol className="ep-run-turns" aria-label="Every turn, oldest first">
          {turns.map((t, i) =>
            t.state === "working" ? (
              <LiveTurn key={t.id} turn={t} n={i + 1} lit={lit === t.id} onLight={onLight} />
            ) : (
              <PastTurn key={t.id} turn={t} n={i + 1} lit={lit === t.id} onLight={onLight} />
            ),
          )}
        </ol>
        {failed && <Stopped view={view} run={run} busy={busy} />}
      </div>
      {!pinned && (
        <button type="button" className="ep-run-latest" onClick={toLatest}>
          Latest
        </button>
      )}
    </section>
  );
}

function PastTurn({ turn, n, lit, onLight }: { turn: EpisodeRun; n: number; lit: boolean; onLight: (id: string | null) => void }) {
  const said = plain(turn.said);
  const took = turn.ended_at ? lasted(turn.ended_at - turn.started_at) : "";
  return (
    <li id={`ep-turn-${turn.id}`} className="ep-run-turn" data-state={turn.state} data-lit={lit || undefined} onPointerEnter={() => onLight(turn.id)} onPointerLeave={() => onLight(null)}>
      <span className="ep-run-turn-mark" aria-hidden="true">
        {turn.state === "done" ? <Check /> : turn.state === "failed" ? <X /> : <Square />}
      </span>
      <div className="ep-run-turn-body">
        <p className="ep-run-turn-head">
          <b>Turn {n}</b>
          <span>
            {turn.steps} {turn.steps === 1 ? "step" : "steps"}
            {took && ` · ${took}`}
          </span>
        </p>
        {said && <p className="ep-run-said">{said}</p>}
      </div>
    </li>
  );
}

// The turn under way, as one line: its steps show under the plan's stage at work.
function LiveTurn({ turn, n, lit, onLight }: { turn: EpisodeRun; n: number; lit: boolean; onLight: (id: string | null) => void }) {
  return (
    <li id={`ep-turn-${turn.id}`} className="ep-run-turn" data-state="working" data-lit={lit || undefined} onPointerEnter={() => onLight(turn.id)} onPointerLeave={() => onLight(null)}>
      <span className="ep-run-turn-mark" aria-hidden="true" />
      <div className="ep-run-turn-body">
        <p className="ep-run-turn-head">
          <b>Turn {n}</b>
          <span>
            Under way · <Elapsed since={turn.started_at} />
          </span>
        </p>
      </div>
    </li>
  );
}

function Stopped({ view, run, busy }: { view: EpisodeView; run: Run; busy: boolean }) {
  const writers = view.options.writers.filter((w) => w.ready);
  const [writer, setWriter] = useState<WriterId>(view.writer);
  return (
    <div className="ep-run-fail">
      <p>{view.stage.said || "The writer stopped before the plan was done."}</p>
      <div className="ep-row">
        <WriterPick writers={writers} value={writer} onChange={setWriter} />
        <button type="button" className="btn primary" disabled={busy} onClick={() => void run(() => api.planAgain(view.id, writer === view.writer ? "" : writer))}>
          <RotateCcw />
          Pick it up
        </button>
      </div>
      <p className="faint">It carries on from the stage it stopped at. Another agent picks up the same files and the record of what was said.</p>
    </div>
  );
}

function WriterPick({ writers, value, onChange }: { writers: EpisodeView["options"]["writers"]; value: WriterId; onChange: (id: WriterId) => void }) {
  return (
    <div className="agents named" role="radiogroup" aria-label="Who writes it">
      {writers.map((w) => (
        <button type="button" role="radio" key={w.id} aria-checked={value === w.id} onClick={() => onChange(w.id)}>
          <AgentMark mark={w.local ? w.id : undefined} size="sm" />
          <span>{w.title}</span>
        </button>
      ))}
    </div>
  );
}

function SoFar({ view }: { view: EpisodeView }) {
  const w = view.written;
  const s = view.settings;
  const beats = w.chapters.reduce((n, c) => n + c.beats, 0);
  const look = view.options.themes.find((t) => t.id === s.theme)?.name;
  return (
    <aside className="ep-run-panel ep-run-so-far" aria-label="Written so far">
      <section>
        <h2>The idea</h2>
        {w.idea ? <p className="ep-run-idea">{w.idea}</p> : <Pending lines={2} note="It comes once the material is read." />}
      </section>
      <section>
        <h2>
          Chapters
          {w.chapters.length > 0 && (
            <small>
              {w.chapters.length} · {beats} beats
            </small>
          )}
        </h2>
        {w.chapters.length ? (
          <ol className="ep-run-chapters">
            {w.chapters.map((c) => (
              <li key={c.id}>
                <span>{c.question}</span>
                <small>{c.beats} beats</small>
              </li>
            ))}
          </ol>
        ) : (
          <Pending lines={3} note="They come as the script is written." />
        )}
      </section>
      <section>
        <h2>Made from</h2>
        <dl className="ep-run-facts">
          <dt>Material</dt>
          <dd>{w.material ? `${w.material} passages` : "Being read"}</dd>
          <dt>Length</dt>
          <dd>{lengthName(s.seconds)}</dd>
          <dt>On camera</dt>
          <dd>{s.presenter === "off" ? "Voice only" : "You present"}</dd>
          <dt>Voice</dt>
          <dd>{voiceName(s)}</dd>
          {look && (
            <>
              <dt>Look</dt>
              <dd>{look}</dd>
            </>
          )}
          <dt>Pictures</dt>
          <dd>{LEVEL_NAMES[s.level]}</dd>
        </dl>
      </section>
    </aside>
  );
}

// Where something will be once the writer has put it down: quiet bars, and what fills them.
function Pending({ lines, note }: { lines: number; note: string }) {
  return (
    <div className="ep-run-pending">
      {Array.from({ length: lines }, (_, i) => (
        <i key={i} aria-hidden="true" />
      ))}
      <small>{note}</small>
    </div>
  );
}
