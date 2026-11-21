// The work the agents do for an episode, as it happens. Written for this house from notes on how
// agent-progress components behave; no other component's source is in it.
//
// - `PictureTrail`: one picture's build as a trail, its builder's steps and notes under the
//   stage it is on, newest last, the older ones folded away, built on the agent library
//   (`components/agent`); `PictureSummary` says how a made one's build went. (The plan's own
//   stages are drawn across the whole screen by `PlanRun`.)
// - `WorkPill`: the pictures in the bar, as one pill with a ring that fills as they are made. It
//   opens onto every picture as a cell, filtered by state, each saying what its builder is on or
//   why it stopped; a cell opens its chapter. (What runs now, and its stop, is the pill before
//   it: Running.tsx.)
import { Check, ChevronDown, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { api, type BuildStageId, type EpisodeUnit, type EpisodeView, type Level, type LiveTurn, type WorkPulse } from "../../api";
import { DOING, PICTURES, pictureState, type PictureState } from "../../episode";
import { useHouse } from "../../store";
import { AgentMark } from "../../ui";
import { AgentTrail, type TrailStage } from "../agent/AgentTrail";
import { RunSummary, type SummaryStage } from "../agent/RunSummary";
import { Steer } from "../agent/Steer";
import { Popover } from "../Popover";
import { type Run } from "./Ask";
import { KindArt } from "./PictureArt";
import { Swap } from "./Tiles";

// How a picture is made, stage by stage, as the yes to making it lists them before it starts:
// motion graphics have each line planned as a shot first, are looked over by their builder once
// their stills are taken, and wait for the person's go on a still of each line (the stage that is
// theirs); a simple one is drawn and checked.
export const BUILD: Record<Level, { id: BuildStageId; label: string; yours?: boolean }[]> = {
  rich: [
    { id: "motion", label: "Plan each shot" },
    { id: "draw", label: "Draw it" },
    { id: "pose", label: "Take a still of each line" },
    { id: "review", label: "Look it over" },
    { id: "go", label: "Your go", yours: true },
  ],
  simple: [
    { id: "draw", label: "Draw it" },
    { id: "pose", label: "Check it" },
  ],
};
// The stages that are the builder's own turns, and when a note left now reaches it.
const TURNS: BuildStageId[] = ["motion", "draw", "review"];
const REACHES: Partial<Record<BuildStageId, string>> = {
  motion: "as it starts planning",
  draw: "as it starts drawing",
  review: "as it looks the picture over",
};

// What a turn of an episode is doing between its steps: what the episode said when it was read,
// or what the house has told since ("plan" for the writer's turn, "picture:<unit>" for a
// picture's builder). Nothing once the turn is over.
export function usePulse(episode: string, lane: string, live: LiveTurn | null | undefined): WorkPulse | null {
  const told = useHouse((s) => s.pulses[`${episode}:${lane}`]);
  if (!live) return null;
  const read = live.pulse ?? null;
  return told && (!read || told.at >= read.at) ? told : read;
}

// One picture being made, as a trail: each stage with how long it took, the one it is on with its
// builder's steps, words and thinking as they come, what its model is at between two of them,
// and the person's notes under the stage that took them in. A motion-graphics picture takes a
// note for its builder's next turn without stopping.
export function PictureTrail({ view, unit, builder, run }: { view: EpisodeView; unit: EpisodeUnit; builder: string; run: Run }) {
  const p = unit.picture;
  const pulse = usePulse(view.id, `picture:${unit.id}`, p.live);
  const cut = useHouse((s) => s.cut);
  const level: Level = p.level || unit.level;
  const order = BUILD[level];
  const waiting = p.status === "queued";
  const kept = new Map(p.stages.map((s) => [s.id, s]));
  // a build from before the house kept its stages says which one it is on by its state alone
  const guessed = p.stages.length ? -1 : guessStage(p, level);
  const steps: TrailStage[] = order.map((s, i) => {
    const got = kept.get(s.id);
    const state = got ? got.state : i < guessed ? "done" : i === guessed && !waiting ? "running" : "pending";
    const turn = TURNS.includes(s.id);
    return {
      id: s.id,
      label: s.label,
      state,
      startedAt: got?.started_at ?? (state === "running" && turn ? p.live?.since : null),
      endedAt: got?.ended_at ?? null,
      // what it is doing; who does it is said once, over the trail
      doing: state === "running" ? DOING[s.id] : undefined,
      working: state === "running" && turn && p.live !== null,
      word: waiting && i === 0 ? `Waiting for ${builder}` : s.yours && state === "pending" ? "Yours" : undefined,
      taken: p.steered.filter((n) => n.stage === s.id).map((n) => ({ id: n.id, text: n.text })),
    };
  });
  // a note reaches the builder at its next turn: the first of its turns after the stage under way
  const at = steps.findIndex((s) => s.state === "running");
  const next = waiting ? order[0]?.id : order.slice(at + 1).find((s) => TURNS.includes(s.id))?.id;
  return (
    <>
      <AgentTrail
        label="How the picture is being made"
        steps={steps}
        events={waiting ? [] : (p.live?.events ?? [])}
        turnSince={p.live?.since ?? null}
        pulse={waiting ? null : pulse}
        tells={p.live?.tells ?? false}
        onStop={() => void api.stopEpisode(view.id, unit.id).catch((e: Error) => useHouse.getState().say(e.message))}
        // over it: who builds it, the build's own clock (which runs on from stage to stage) and
        // how many of its stages are done
        agent={{ name: builder.slice(0, 1).toUpperCase() + builder.slice(1), mark: <AgentMark mark={p.builder || unit.builder} size="sm" /> }}
        total={!waiting && p.timing?.started_at ? { since: p.timing.started_at, seconds: p.timing.seconds } : null}
        count
        cut={cut}
      />
      {p.steerable && next && (
        <Steer
          queued={p.queued}
          reaches={`${builder} ${REACHES[next] ?? "at its next turn"}`}
          onQueue={(text) => run(() => api.steerPicture(view.id, unit.id, text))}
          onTakeBack={(id) => run(() => api.unsteerPicture(view.id, unit.id, id))}
        />
      )}
    </>
  );
}

// Which stage a build is on, from the picture's state alone.
function guessStage(p: EpisodeUnit["picture"], level: Level): number {
  const stage = p.status === "posing" ? "pose" : p.status === "go" ? "go" : level === "rich" && !p.motion ? "motion" : "draw";
  return Math.max(0, BUILD[level].findIndex((s) => s.id === stage));
}

// How a made picture's build went: each of its stages that has a time (the go is the person's
// and has none), what its builder said when it looked the picture over, and the notes it took in.
export function PictureSummary({ unit }: { unit: EpisodeUnit }) {
  const p = unit.picture;
  const stages: SummaryStage[] = BUILD[p.level || unit.level].flatMap((s) => {
    const got = p.stages.find((x) => x.id === s.id);
    return got?.state === "done" && got.started_at && got.ended_at ? [{ id: s.id, label: s.label, seconds: got.ended_at - got.started_at }] : [];
  });
  return <RunSummary stages={stages} reviewed={p.reviewed} notes={p.steered} seconds={p.timing?.seconds} />;
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
  return (
    <span className="ep-work">
      <button ref={pill} type="button" className="ep-work-pill" data-tone={tone} aria-haspopup="dialog" aria-expanded={open} aria-label={`Pictures: ${words}`} onClick={() => setOpen((o) => !o)}>
        <Ring value={ready / (count.making > 0 ? asked : units.length)} />
        <Swap swapKey={words} className="ep-work-words">
          {words}
        </Swap>
        <ChevronDown />
      </button>
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
