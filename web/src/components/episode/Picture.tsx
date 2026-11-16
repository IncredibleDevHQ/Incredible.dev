// A picture's card at the head of its block in a chapter's script: the picture itself, a
// placeholder until it is made, beside what it is, how it is made and where it stands. A
// picture is asked for here, on its own (or with its chapter's, by recording the chapter, or
// with the whole film's, from the bar). It is simple (drawn at once from the plan) or rich
// (its motion planned shot by shot, then drawn and posed as stills for a go). A pick never draws
// anything: a picture made before it is out of date until the person applies their changes or
// draws it again here, and drawing a made picture again says what it costs first. A chapter's
// pictures are built by the agent picked for the chapter; one can be drawn by another.
import { ChevronDown, RotateCcw, Sparkles, Square } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { api, type EpisodeFrame, type EpisodeUnit, type EpisodeView, type Level, type Motion, type WriterId } from "../../api";
import { pictureState, pictureWords } from "../../episode";
import { Popover } from "../Popover";
import { SegmentedControl } from "../SegmentedControl";
import { Select } from "../Select";
import type { Run } from "./Ask";
import { AgentMark } from "../../ui";
import { blockName, KindIcon, type Block } from "./Blocks";
import { Changed } from "./Diff";
import { WRITERS } from "./Film";
import { KindArt } from "./PictureArt";

// The agents that are ready on this computer, as a select lists them: each by its mark and name.
export const agentOptions = (view: EpisodeView) =>
  view.options.writers.filter((w) => w.ready).map((w) => ({ value: w.id, label: w.title, icon: <AgentMark mark={w.local ? w.id : undefined} size="sm" /> }));

const LEVELS: Record<Level, string> = {
  rich: "Its motion is planned shot by shot, then it is drawn and posed as stills for your go.",
  simple: "Drawn at once from the plan.",
};

// What planning a picture again costs: the writer's turn, then its builder's full run.
export function planCost(unit: EpisodeUnit, writer: string): string {
  const builder = WRITERS[unit.builder] ?? unit.builder;
  const by = WRITERS[writer] ?? writer;
  return `${by.slice(0, 1).toUpperCase() + by.slice(1)} fits it to your words, then ${builder} draws it again: two runs, so the tokens are spent again.`;
}

// What drawing a made picture again costs, said before it is done: another full run of its
// agent, so its tokens are spent again.
export function againCost(units: EpisodeUnit[]): string {
  const names = [...new Set(units.map((u) => WRITERS[u.builder] ?? u.builder))];
  const rich = units.some((u) => u.level === "rich");
  const who = names.length === 1 ? names[0] : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  return `${units.length === 1 ? "It is" : "Each is"} another full run of ${who}${rich ? ", and a rich picture plans its motion first" : ""}, so the tokens are spent again.`;
}

export function PictureCard({
  view,
  block,
  lines,
  picked,
  onPick,
  onOpen,
  run,
  busy,
  tools,
}: {
  view: EpisodeView;
  block: Block & { unit: EpisodeUnit };
  // every line of the chapter, and the one that is picked
  lines: EpisodeFrame[];
  picked: string;
  onPick: (frame: string) => void;
  // opens the frame, its choices and the recorder on this picture
  onOpen: () => void;
  run: Run;
  busy: boolean;
  // what else the block's head holds: taking the block out
  tools?: ReactNode;
}) {
  const unit = block.unit;
  const p = unit.picture;
  const state = pictureState(unit, view);
  const designed = unit.kind === "picture";
  const name = blockName(block);
  // the picture as it ends: its last line's still
  const still = p.stills[unit.frames[unit.frames.length - 1]] ?? Object.values(p.stills).pop();
  // Drawing a made picture again, or planning it again, waits for a yes that knows what it costs.
  const [asking, setAsking] = useState<"draw" | "plan" | null>(null);
  const again = asking === "draw";
  const setAgain = (on: boolean) => setAsking(on ? "draw" : null);
  const choose = (pick: { level?: Level; builder?: WriterId | null }) => run(() => api.chooseEpisode(view.id, { units: { [unit.id]: pick } }));
  const make = () => void run(() => api.makePictures(view.id, { units: [unit.id] }));
  const level = (next: Level) => next !== unit.level && void choose({ level: next });
  // A picture that was not made can be tried with another agent than its chapter's.
  const agents = agentOptions(view);
  const builder = agents.length > 1 && (
    <label className="ep-figure-by">
      with
      <Select
        size="sm"
        aria-label="The agent that makes this picture"
        value={unit.builder}
        options={agents}
        disabled={busy}
        onChange={(id) => id !== unit.builder && void choose({ builder: id === view.builders[unit.chapter] ? null : (id as WriterId) })}
      />
    </label>
  );

  return (
    <>
      <div className="ep-figure-top">
        <button
          type="button"
          className="ep-figure-pic"
          data-empty={!still || undefined}
          data-working={(designed && state === "making") || undefined}
          aria-label={`Open the ${name.toLowerCase()} with its choices`}
          onClick={onOpen}
        >
          {still ? <img src={still.url} alt="" loading="lazy" /> : <KindArt kind={unit.kind_of_picture} />}
        </button>
        <div className="ep-figure-meta">
          <header className="ep-block-head" data-status={state}>
            <KindIcon block={block} />
            <b>{name}</b>
            <span>{pictureWords(unit, view)}</span>
            {p.motion && <MotionPlan motion={p.motion} lines={lines} />}
            {designed && (
              <SegmentedControl<Level>
                size="sm"
                aria-label={`How the ${name.toLowerCase()} is made`}
                className="ep-figure-level"
                value={unit.level}
                disabled={busy || state === "making"}
                onChange={level}
                options={[
                  { value: "simple", label: "Simple" },
                  { value: "rich", label: "Rich" },
                ]}
              />
            )}
            {tools}
          </header>
          {unit.shows && <p className="ep-block-shows">{unit.shows}</p>}
          {!designed ? (
            state === "changed" && <p className="ep-figure-note">Apply your changes in the bar and the writer plans it.</p>
          ) : state === "planned" ? (
            <div className="ep-figure-act">
              <button type="button" className="btn" disabled={busy} onClick={make}>
                <Sparkles />
                Generate
              </button>
              <small>
                {LEVELS[unit.level]}
                {unit.level === "simple" && unit.suggest === "rich" ? " Rich is suggested for this one." : ""}
              </small>
            </div>
          ) : state === "changed" ? (
            again ? (
              <p
                className="ep-confirm"
                role="alertdialog"
                aria-label="Draw it again"
                onKeyDown={(e) => {
                  if (e.key !== "Escape") return;
                  e.stopPropagation();
                  setAgain(false);
                }}
              >
                <span>{againCost([unit])}</span>
                <button
                  type="button"
                  className="btn primary"
                  autoFocus
                  disabled={busy}
                  onClick={() => {
                    setAgain(false);
                    make();
                  }}
                >
                  Draw it again
                </button>
                <button type="button" className="btn" onClick={() => setAgain(false)}>
                  Cancel
                </button>
              </p>
            ) : (
              <div className="ep-figure-act">
                <button type="button" className="btn" disabled={busy} onClick={() => setAgain(true)}>
                  <RotateCcw />
                  Draw it again
                </button>
                {builder}
                <small>or apply all your changes from the bar.</small>
              </div>
            )
          ) : state === "reworded" ? (
            asking ? (
              <p
                className="ep-confirm"
                role="alertdialog"
                aria-label={asking === "plan" ? "Plan it again" : "Draw it again"}
                onKeyDown={(e) => {
                  if (e.key !== "Escape") return;
                  e.stopPropagation();
                  setAsking(null);
                }}
              >
                <span>{asking === "plan" ? planCost(unit, view.settings.writer) : againCost([unit])}</span>
                <button
                  type="button"
                  className="btn primary"
                  autoFocus
                  disabled={busy}
                  onClick={() => {
                    const plan = asking === "plan";
                    setAsking(null);
                    if (plan) void run(() => api.replanPictures(view.id, [unit.id]));
                    else make();
                  }}
                >
                  {asking === "plan" ? "Plan it again" : "Draw it again"}
                </button>
                <button type="button" className="btn" onClick={() => setAsking(null)}>
                  Cancel
                </button>
              </p>
            ) : (
              <>
                <div className="ep-figure-act" data-tone="amber">
                  <button type="button" className="btn" disabled={busy} onClick={() => setAsking("plan")}>
                    <Sparkles />
                    Plan it again
                  </button>
                  <button type="button" className="btn" disabled={busy} onClick={() => setAsking("draw")}>
                    <RotateCcw />
                    Draw it again
                  </button>
                  <button type="button" className="linkish" disabled={busy} onClick={() => void run(() => api.keepPicture(view.id, unit.id))}>
                    Keep it
                  </button>
                </div>
                <WhatChanged madeFor={p.made_for} lines={lines} />
              </>
            )
          ) : state === "making" ? (
            <div className="ep-figure-act" role="status">
              <span className="spin" />
              {/* the step its builder is on; where it stands is said once, in the head */}
              <span className="ep-figure-doing">{p.doing}</span>
              <button type="button" className="linkish" onClick={() => void api.stopEpisode(view.id, unit.id).catch(() => undefined)}>
                <Square />
                Stop
              </button>
            </div>
          ) : state === "failed" ? (
            <div className="ep-figure-act" data-tone="red">
              <span className="ep-figure-doing">{p.failure || "It stopped."}</span>
              <button type="button" className="btn" disabled={busy} onClick={make}>
                <RotateCcw />
                Try again
              </button>
              {builder}
            </div>
          ) : null}
        </div>
      </div>
      {state === "go" && <Stills view={view} unit={unit} lines={lines} picked={picked} onPick={onPick} run={run} busy={busy} />}
    </>
  );
}

// What a picture made for other words was made for, a click away: each line that says something
// else now, its words then against its words now, read-only (the words are the person's own).
function WhatChanged({ madeFor, lines }: { madeFor: Record<string, string>; lines: EpisodeFrame[] }) {
  const changed = lines.filter((l) => madeFor[l.id] !== undefined);
  if (!changed.length) return <small className="ep-figure-note">Made for the words before. It still plays, timed to the new ones.</small>;
  return (
    <details className="ep-what-changed">
      <summary>Made for the words before · what changed in {changed.length === 1 ? "1 line" : `${changed.length} lines`}</summary>
      <ol>
        {changed.map((l) => (
          <li key={l.id}>
            <small>Line {lines.indexOf(l) + 1}</small>
            <Changed was={madeFor[l.id]} now={l.vo} />
          </li>
        ))}
      </ol>
    </details>
  );
}

// A rich picture's motion plan, a click away from its block: how the picture carries its idea
// and where it happens, then each line's shot as its builder planned it (what it opens on, the
// move the line is about, what lands around it, what it ends on).
function MotionPlan({ motion, lines }: { motion: Motion; lines: EpisodeFrame[] }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={button} type="button" className="ep-figure-plan" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Motion plan
        <ChevronDown aria-hidden="true" />
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchor={button}
        side="bottom"
        align="start"
        offset={8}
        width={540}
        className="ep-plan-pop"
        title={motion.device.slice(0, 1).toUpperCase() + motion.device.slice(1)}
        description={motion.world}
      >
        <ol className="ep-plan-shots">
          {motion.shots.map((shot) => (
            <li key={shot.frame}>
              <b>
                Line {lines.findIndex((l) => l.id === shot.frame) + 1}
                {shot.shot ? ` · ${shot.shot}` : ""}
              </b>
              <dl>
                {shot.opens_on && (
                  <>
                    <dt>Opens on</dt>
                    <dd>{shot.opens_on}</dd>
                  </>
                )}
                <dt>The move</dt>
                <dd>{shot.hero}</dd>
                {shot.others && (
                  <>
                    <dt>Around it</dt>
                    <dd>{shot.others}</dd>
                  </>
                )}
                <dt>Ends on</dt>
                <dd>{shot.still}</dd>
              </dl>
            </li>
          ))}
        </ol>
      </Popover>
    </>
  );
}

// A rich picture's stills, one for the end of each of its lines, waiting for the person's go:
// they give it, or say what should change.
export function Stills({
  view,
  unit,
  lines,
  picked,
  onPick,
  run,
  busy,
}: {
  view: EpisodeView;
  unit: EpisodeUnit;
  lines: EpisodeFrame[];
  picked: string;
  onPick: (frame: string) => void;
  run: Run;
  busy: boolean;
}) {
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  const p = unit.picture;
  if (p.status !== "go") return null;
  const mine = lines.filter((l) => unit.frames.includes(l.id));
  const send = () => {
    if (!note.trim()) return;
    void run(() => api.askEpisode(view.id, { scope: "picture", target: unit.id, text: note.trim() })).then((taken) => {
      if (!taken) return;
      setNote("");
      setNoting(false);
    });
  };
  return (
    <div className="ep-stills">
      <div className="ep-stills-row">
        {mine.map((l) => {
          const still = p.stills[l.id];
          return (
            <button type="button" key={l.id} aria-current={l.id === picked || undefined} aria-label={`The still for line ${lines.indexOf(l) + 1}`} onClick={() => onPick(l.id)}>
              {still && <img src={still.url} alt="" loading="lazy" />}
            </button>
          );
        })}
      </div>
      {noting ? (
        <div className="ep-stills-note">
          <textarea
            autoFocus
            rows={2}
            value={note}
            placeholder="What should change?"
            aria-label="What should change?"
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
            }}
          />
          <button type="button" className="btn" onClick={() => setNoting(false)}>
            Cancel
          </button>
          <button type="button" className="btn primary" disabled={busy || !note.trim()} onClick={send}>
            Send it back
          </button>
        </div>
      ) : (
        <div className="ep-stills-act">
          <span>These stills are how the picture ends each line.</span>
          <button type="button" className="btn" disabled={busy} onClick={() => setNoting(true)}>
            Send a note
          </button>
          <button type="button" className="btn primary" disabled={busy} onClick={() => void run(() => api.pictureGo(view.id, unit.id))}>
            Give the go
          </button>
        </div>
      )}
    </div>
  );
}
