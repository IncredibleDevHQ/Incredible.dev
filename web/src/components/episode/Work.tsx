// The work the agents do for an episode, as it happens. Written for this house from notes on how
// agent-progress components behave; no other component's source is in it.
//
// - `WorkTrail`: the plan's stages as a trail. The stage under way opens onto what the writer is
//   doing in it: its steps and its own notes, newest last, the older ones folded away.
// - `PictureTrail`: one picture's build as the same trail, its builder's steps and notes under
//   the stage it is on.
// - `WorkPill`: the pictures in the bar, as one pill with a ring that fills as they are made. It
//   opens onto every picture as a cell, filtered by state, each saying what its builder is on or
//   why it stopped; a cell opens its chapter.
import { Check, ChevronDown, RotateCcw, Square, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { api, type EpisodeUnit, type EpisodeView, type Level, type WorkEvent } from "../../api";
import { PICTURES, pictureState, type PictureState } from "../../episode";
import { useHouse } from "../../store";
import { Popover } from "../Popover";
import { Elapsed, type Run } from "./Ask";
import { KindArt } from "./PictureArt";
import { Swap } from "./Tiles";

// How many of the writer's latest steps and notes show before the older ones fold away.
const SHOWN = 5;

export function WorkTrail({ view }: { view: EpisodeView }) {
  const stage = view.stage;
  const failed = view.status === "failed";
  const current = stage.name === "done" ? "done" : stage.name === "redo" || stage.name === "fix" ? "frames" : (stage.name ?? "brief");
  const at =
    current === "done"
      ? view.steps.length
      : Math.max(
          0,
          view.steps.findIndex((s) => s.id === current),
        );
  const events = view.working?.events ?? [];
  const [all, setAll] = useState(false);
  const folded = all ? 0 : Math.max(0, events.length - SHOWN);
  const shown = events.slice(folded);
  const checking = stage.state === "reading";

  // What a screen reader hears: a stage that finishes or stops, said once.
  const [heard, setHeard] = useState("");
  const was = useRef(at);
  useEffect(() => {
    if (at > was.current) setHeard(`${view.steps[at - 1]?.label ?? "A stage"}: done`);
    was.current = at;
  }, [at, view.steps]);
  useEffect(() => {
    if (failed) setHeard(`${view.steps[at]?.label ?? "The plan"}: stopped`);
  }, [failed, at, view.steps]);

  return (
    <div className="ep-trail">
      <ol aria-label="The plan, stage by stage">
        {view.steps.map((s, i) => {
          const state = i < at ? "done" : i === at ? (failed ? "failed" : "running") : "next";
          const open = state === "running" && !checking && shown.length > 0;
          return (
            <li key={s.id} className="ep-trail-step" data-state={state} data-open={open || undefined} aria-current={state === "running" ? "step" : undefined}>
              <span className="ep-trail-row">
                <span className="ep-trail-mark" aria-hidden="true">
                  {state === "done" ? <Check /> : state === "failed" ? <X /> : null}
                </span>
                <span className="ep-trail-title">{s.label}</span>
                <span className="ep-trail-meta">
                  {state === "running" && (
                    <>
                      <Swap swapKey={checking ? "checking" : (stage.round ?? 0) > 0 ? `fix-${stage.round}` : "writing"} className="ep-trail-doing">
                        {checking ? "Checking" : (stage.round ?? 0) > 0 ? `Fixing · round ${stage.round}` : "Writing"}
                      </Swap>
                      {stage.at && <Elapsed since={stage.at} />}
                    </>
                  )}
                  {state === "failed" && "Stopped"}
                </span>
              </span>
              {open && (
                <div className="ep-trail-branch" aria-label={`What ${view.working?.harness ? "the writer" : "it"} is doing`}>
                  {events.length > SHOWN && (
                    <button type="button" className="ep-trail-fold" aria-expanded={all} onClick={() => setAll((a) => !a)}>
                      {all ? "Show fewer" : `+${folded} earlier`}
                    </button>
                  )}
                  <ol>
                    {shown.map((e, n) => (
                      <TrailEvent key={`${e.at}-${n + folded}`} event={e} latest={n === shown.length - 1} />
                    ))}
                  </ol>
                </div>
              )}
            </li>
          );
        })}
      </ol>
      <span className="sr-only" role="status" aria-live="polite">
        {heard}
      </span>
    </div>
  );
}

// How a picture is made, stage by stage, as the yes to making it lists them before it starts:
// motion graphics have each line planned as a shot first and wait for the person's go on a still
// of each line at the end (the stage that is theirs); a simple one is drawn and checked.
export const BUILD: Record<Level, { id: string; label: string; yours?: boolean }[]> = {
  rich: [
    { id: "motion", label: "Plan each shot" },
    { id: "draw", label: "Draw it" },
    { id: "pose", label: "Take a still of each line" },
    { id: "go", label: "Your go", yours: true },
  ],
  simple: [
    { id: "draw", label: "Draw it" },
    { id: "pose", label: "Check it" },
  ],
};

// One picture being made, as a trail: the stage it is on opens onto its builder's steps and
// notes as they happen, the older ones folded away. One that waits for its builder (another
// picture of the builder's is being made) says so on its first stage.
export function PictureTrail({ unit, builder }: { unit: EpisodeUnit; builder: string }) {
  const p = unit.picture;
  const level: Level = p.level || unit.level;
  const steps = BUILD[level];
  const stage = p.status === "posing" ? "pose" : p.status === "go" ? "go" : level === "rich" && !p.motion ? "motion" : "draw";
  const waiting = p.status === "queued";
  const at = waiting
    ? 0
    : Math.max(
        0,
        steps.findIndex((s) => s.id === stage),
      );
  const events = waiting ? [] : (p.live?.events ?? []);
  const [all, setAll] = useState(false);
  const folded = all ? 0 : Math.max(0, events.length - SHOWN);
  const shown = events.slice(folded);

  // What a screen reader hears: a stage that finishes, said once.
  const [heard, setHeard] = useState("");
  const was = useRef(at);
  useEffect(() => {
    if (at > was.current) setHeard(`${steps[at - 1]?.label ?? "A stage"}: done`);
    was.current = at;
  }, [at, steps]);

  return (
    <div className="ep-trail ep-build-trail">
      <ol aria-label="How the picture is being made">
        {steps.map((s, i) => {
          const state = i < at ? "done" : i === at ? (waiting ? "next" : "running") : "next";
          const open = state === "running" && shown.length > 0;
          return (
            <li key={s.id} className="ep-trail-step" data-state={state} data-open={open || undefined} aria-current={i === at ? "step" : undefined}>
              <span className="ep-trail-row">
                <span className="ep-trail-mark" aria-hidden="true">
                  {state === "done" ? <Check /> : null}
                </span>
                <span className="ep-trail-title">{s.label}</span>
                <span className="ep-trail-meta">
                  {i === at && waiting && `Waiting for ${builder}`}
                  {state === "running" &&
                    (p.live ? (
                      <>
                        <span className="ep-trail-doing">{builder}</span>
                        <Elapsed since={p.live.since} />
                      </>
                    ) : (
                      // between the builder's turns the house renders and checks on its own
                      <span className="ep-trail-doing">{s.id === "pose" ? "Rendering" : builder}</span>
                    ))}
                </span>
              </span>
              {open && (
                <div className="ep-trail-branch" aria-label={`What ${builder} is doing`}>
                  {events.length > SHOWN && (
                    <button type="button" className="ep-trail-fold" aria-expanded={all} onClick={() => setAll((a) => !a)}>
                      {all ? "Show fewer" : `+${folded} earlier`}
                    </button>
                  )}
                  <ol>
                    {shown.map((e, n) => (
                      <TrailEvent key={`${e.at}-${n + folded}`} event={e} latest={n === shown.length - 1} />
                    ))}
                  </ol>
                </div>
              )}
            </li>
          );
        })}
      </ol>
      <span className="sr-only" role="status" aria-live="polite">
        {heard}
      </span>
    </div>
  );
}

function TrailEvent({ event, latest }: { event: WorkEvent; latest: boolean }) {
  // a step is what the writer did (a file read, an edit); a note is the writer in its own words
  return event.kind === "note" ? (
    <li className="ep-trail-note" data-latest={latest || undefined}>
      <q>{event.text}</q>
    </li>
  ) : (
    <li className="ep-trail-sub" data-latest={latest || undefined} title={event.text}>
      <span>{event.text}</span>
    </li>
  );
}

const STATE_WORDS: Record<PictureState, string> = {
  made: "Made",
  making: "Being made",
  go: "Needs your go",
  changed: "Out of date",
  reworded: "Made for other words",
  failed: "Not made",
  planned: "Not asked for yet",
};
const stateOf = pictureState;

// One pill for the pictures, beside what can be done about them now.
export function WorkPill({ view, run, busy, onAt }: { view: EpisodeView; run: Run; busy: boolean; onAt: (chapter: string) => void }) {
  const units = useMemo(() => view.units.filter((u) => u.kind === "picture"), [view.units]);
  const count: Record<PictureState, number> = { made: 0, making: 0, go: 0, changed: 0, reworded: 0, failed: 0, planned: 0 };
  for (const u of units) count[stateOf(u)] += 1;
  const [open, setOpen] = useState(false);
  const pill = useRef<HTMLButtonElement>(null);
  if (units.length === 0) return null;
  // a picture out of date is made: it counts until it is drawn again
  const ready = count.made + count.go + count.changed;
  // while pictures are on their way, how far the ones asked for are; after, how many stand
  const asked = units.length - count.planned;
  const words =
    count.making > 0
      ? `${ready} of ${asked} pictures`
      : count.failed > 0
        ? `${count.failed} ${count.failed === 1 ? "picture" : "pictures"} not made`
        : count.go > 0
          ? `${count.go} ${count.go === 1 ? "needs" : "need"} your go`
          : count.changed > 0
            ? `${count.changed} out of date`
            : count.planned > 0
              ? `${ready} of ${units.length} pictures made`
              : `${units.length} pictures made`;
  const tone = count.making > 0 ? "making" : count.failed > 0 ? "failed" : count.go > 0 || count.changed > 0 ? "go" : "made";
  const stop = () => void api.stopEpisode(view.id).catch((e: Error) => useHouse.getState().say(e.message));
  return (
    <span className="ep-work">
      <button ref={pill} type="button" className="ep-work-pill" data-tone={tone} aria-haspopup="dialog" aria-expanded={open} aria-label={`Pictures: ${words}`} onClick={() => setOpen((o) => !o)}>
        <Ring value={ready / (count.making > 0 ? asked : units.length)} />
        <Swap swapKey={words} className="ep-work-words">
          {words}
        </Swap>
        <ChevronDown />
      </button>
      {count.making > 0 && (
        <button type="button" className="btn" onClick={stop}>
          <Square />
          Stop
        </button>
      )}
      {count.making === 0 && count.failed > 0 && (
        <button type="button" className="btn" disabled={busy} onClick={() => void run(() => api.makePictures(view.id))}>
          <RotateCcw />
          {count.failed === 1 ? "Make it" : "Make them"}
        </button>
      )}
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchor={pill}
        side="bottom"
        align="end"
        offset={8}
        width={440}
        className="ep-work-pop"
        title="Pictures"
        description={`${ready} of ${units.length} made`}
      >
        <PictureGrid
          view={view}
          units={units}
          count={count}
          onOpen={(u) => {
            setOpen(false);
            onAt(u.chapter);
          }}
        />
      </Popover>
    </span>
  );
}

// How full the pictures are: a ring that fills clockwise from the top.
function Ring({ value }: { value: number }) {
  const r = 6;
  const c = 2 * Math.PI * r;
  const v = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  return (
    <svg className="ep-ring" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r={r} className="ep-ring-track" />
      <circle cx="8" cy="8" r={r} className="ep-ring-fill" strokeDasharray={c} strokeDashoffset={c * (1 - v)} />
    </svg>
  );
}

// Every picture as a cell, in the film's order. The arrow keys walk the cells (up and down by
// the row as it is laid out), Enter opens a cell's chapter, and the counts under the grid show
// one state at a time.
function PictureGrid({ view, units, count, onOpen }: { view: EpisodeView; units: EpisodeUnit[]; count: Record<PictureState, number>; onOpen: (unit: EpisodeUnit) => void }) {
  const [only, setOnly] = useState<PictureState | null>(null);
  const [shown, setShown] = useState<number | null>(null);
  const [stop, setStop] = useState(0);
  const cells = useRef<(HTMLButtonElement | null)[]>([]);
  const chapters = view.plan?.chapters ?? [];
  const number = (u: EpisodeUnit) => chapters.findIndex((c) => c.id === u.chapter) + 1;
  const words = (u: EpisodeUnit) => (view.plan?.chapters.flatMap((c) => c.beats.flatMap((b) => b.frames)).find((f) => f.id === u.frames[0])?.vo ?? "").slice(0, 140);

  const go = (from: number, key: string) => {
    const n = units.length;
    // a row is as many cells as share the first cell's top, however wide the grid is laid out
    const top = cells.current[0]?.offsetTop ?? 0;
    const row = Math.max(1, cells.current.filter((c) => c && c.offsetTop === top).length);
    const to = key === "ArrowRight" ? from + 1 : key === "ArrowLeft" ? from - 1 : key === "ArrowDown" ? from + row : key === "ArrowUp" ? from - row : key === "Home" ? 0 : n - 1;
    const next = Math.min(n - 1, Math.max(0, to));
    cells.current[next]?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, at: number) => {
    if (e.altKey || e.ctrlKey || e.metaKey || !["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    go(at, e.key);
  };

  // What a screen reader hears: a picture that lands made, waiting for a go, or stopped.
  const [heard, setHeard] = useState("");
  const before = useRef(new Map(units.map((u) => [u.id, stateOf(u)])));
  useEffect(() => {
    const said: string[] = [];
    for (const u of units) {
      const now = stateOf(u);
      if (before.current.get(u.id) !== now && now !== "making") said.push(`Chapter ${number(u)}, ${PICTURES[u.kind_of_picture] ?? "picture"}: ${STATE_WORDS[now].toLowerCase()}`);
      before.current.set(u.id, now);
    }
    if (said.length) setHeard(said.join(". "));
  });

  const focused = shown !== null ? units[shown] : undefined;
  return (
    <div className="ep-pics-wrap">
      <div className="ep-pics" role="group" aria-label="The pictures, in the film's order" onPointerLeave={() => setShown(null)}>
        {units.map((u, i) => {
          const state = stateOf(u);
          const still = u.picture.stills[u.frames[0]];
          return (
            <button
              key={u.id}
              ref={(el) => {
                cells.current[i] = el;
              }}
              type="button"
              className="ep-pic"
              data-state={state}
              data-dim={(only && only !== state) || undefined}
              tabIndex={i === stop ? 0 : -1}
              aria-label={`Chapter ${number(u)}, ${PICTURES[u.kind_of_picture] ?? "picture"}: ${STATE_WORDS[state]}`}
              onClick={() => onOpen(u)}
              onPointerEnter={() => setShown(i)}
              onFocus={() => {
                setShown(i);
                setStop(i);
              }}
              onBlur={() => setShown(null)}
              onKeyDown={(e) => onKey(e, i)}
              style={{ "--i": i } as React.CSSProperties}
            >
              <span className="ep-pic-art" aria-hidden="true">
                {still ? <img src={still.url} alt="" loading="lazy" /> : <KindArt kind={u.kind_of_picture} />}
              </span>
              <span className="ep-pic-badge" aria-hidden="true">
                {state === "made" ? <Check /> : state === "failed" ? <X /> : state === "go" ? "Go" : null}
              </span>
              <b className="ep-pic-num" aria-hidden="true">
                {number(u)}
              </b>
            </button>
          );
        })}
      </div>
      <Swap swapKey={focused ? focused.id : "none"} className="ep-pic-detail" hidden>
        {focused ? (
          <>
            <b>
              Chapter {number(focused)} · {PICTURES[focused.kind_of_picture] ?? "Picture"}
            </b>
            <span data-state={stateOf(focused)}>
              {STATE_WORDS[stateOf(focused)]}
              {stateOf(focused) === "making" && focused.picture.doing ? ` · ${focused.picture.doing}` : ""}
            </span>
            {stateOf(focused) === "failed" && focused.picture.failure ? <em>{focused.picture.failure}</em> : <small>“{words(focused)}”</small>}
          </>
        ) : (
          <small>Point at a picture to see where it stands. A click opens its chapter.</small>
        )}
      </Swap>
      <div className="ep-pics-counts" role="group" aria-label="Show only">
        {(["made", "making", "go", "changed", "reworded", "failed", "planned"] as PictureState[])
          .filter((s) => s === "made" || count[s] > 0)
          .map((s) => (
            <button key={s} type="button" aria-pressed={only === s} data-state={s} data-quiet={(only && only !== s) || undefined} onClick={() => setOnly(only === s ? null : s)}>
              <i aria-hidden="true" />
              <b>{count[s]}</b> {STATE_WORDS[s].toLowerCase()}
            </button>
          ))}
      </div>
      <span className="sr-only" role="status" aria-live="polite">
        {heard}
      </span>
    </div>
  );
}
