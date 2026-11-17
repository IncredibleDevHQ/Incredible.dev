// A picture's card at the head of its block in a chapter's script: the picture itself, a
// placeholder until it is made, beside what it is, how it is made and where it stands. A
// picture is asked for here, on its own (or with its chapter's, by recording the chapter, or
// with the whole film's, from the bar). It is simple (drawn at once from the plan) or motion
// graphics (each line planned as a shot, then drawn, with a still of each line for a go). A pick
// never draws anything: a picture made before it is out of date until the person applies their
// changes or draws it again here, and drawing a made picture again says what it costs first.
// Changing how a made picture is made is that same yes: before it starts it lists the stages to
// come, the one that waits on the person among them, what it costs and who makes it, and the yes
// makes it again at once. While a picture is made, its card follows the build stage by stage, its
// builder's steps and notes as they happen. A made picture plays in its card once its clip is
// rendered, and the go on motion graphics says what it did: the picture was built before its
// stills, so the go puts it in the film and nothing more is made. A chapter's pictures are built
// by the agent picked for the chapter; one can be drawn by another.
import { Check, ChevronDown, Play, RotateCcw, Sparkles, Square } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, type EpisodeFrame, type EpisodeUnit, type EpisodeView, type Level, type Motion } from "../../api";
import { LEVEL_NAMES, pictureState, pictureWords } from "../../episode";
import { Popover } from "../Popover";
import { SegmentedControl } from "../SegmentedControl";
import type { Run } from "./Ask";
import { blockName, KindIcon, type Block } from "./Blocks";
import { Changed } from "./Diff";
import { WRITERS } from "./Film";
import { BUILD, PictureTrail } from "./Work";
import { GenerationSettings } from "./GenerationSettings";
import { KindArt } from "./PictureArt";

const LEVELS: Record<Level, string> = {
  rich: "Each line is planned as a shot, then drawn. You play it and check a still of each line before your go.",
  simple: "Drawn at once from the plan.",
};

// What planning a picture again costs: the writer's turn, then its builder's full run.
export function planCost(unit: EpisodeUnit, writer: string): string {
  const builder = WRITERS[unit.builder] ?? unit.builder;
  const by = WRITERS[writer] ?? writer;
  return `${by.slice(0, 1).toUpperCase() + by.slice(1)} fits it to your words, then ${builder} draws it again: two runs, so the tokens are spent again.`;
}

// What making a made picture another way asks of the person and costs, said before it is done
// under the stages its builder goes through: what comes back to them (a still of each line to
// check, or nothing), and another full run of its builder.
export function levelCost(unit: EpisodeUnit, to: Level): string {
  const builder = WRITERS[unit.builder] ?? unit.builder;
  return to === "rich"
    ? `You play it and check a still of each line before your go puts it in the film. Another full run of ${builder}, so the tokens are spent again.`
    : `No shots to plan and no stills to check: it goes straight into the film. Another full run of ${builder}, so the tokens are spent again.`;
}

// What drawing a made picture again costs, said before it is done: another full run of its
// agent, so its tokens are spent again.
export function againCost(units: EpisodeUnit[]): string {
  const names = [...new Set(units.map((u) => WRITERS[u.builder] ?? u.builder))];
  const rich = units.some((u) => u.level === "rich");
  const who = names.length === 1 ? names[0] : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  return `${units.length === 1 ? "It is" : "Each is"} another full run of ${who}${rich ? ", and motion graphics plan each shot first" : ""}, so the tokens are spent again.`;
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
  // The picture moving, in its card: its draft clip, once one is rendered for it as made. What
  // plays is held by the clip's address, so a clip rendered for a later make never starts alone.
  const clip = p.status === "made" || p.status === "go" ? p.clip : null;
  const [preview, setPreview] = useState<{source: string; url: string} | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [playError, setPlayError] = useState("");
  const moving = Boolean(preview && clip && preview.source === clip.id);
  const play = async () => {
    if (moving) { setPreview(null); return; }
    if (!clip || preparing) return;
    setPreparing(true);
    setPlayError("");
    try {
      const ready = await api.previewPicture(view.id, unit.id);
      setPreview({source: clip.id, url: ready.url});
    } catch (error) {
      setPlayError((error as Error).message);
    } finally {
      setPreparing(false);
    }
  };
  // Drawing a made picture again, or planning it again, waits for a yes that knows what it costs.
  const [asking, setAsking] = useState<"draw" | "plan" | null>(null);
  // The way the person switched a made picture to, while they say yes to making it so; and the
  // one they said yes to, until the plan has it.
  const levelAnchor = useRef<HTMLDivElement>(null);
  const [toLevel, setToLevel] = useState<Level | null>(null);
  const [sent, setSent] = useState<Level | null>(null);
  const again = asking === "draw";
  const setAgain = (on: boolean) => setAsking(on ? "draw" : null);
  const make = () => void run(() => api.makePictures(view.id, { units: [unit.id] }));
  // The switch says how the picture is made: a made one as it was built (one made before that was
  // kept is rich when it has a motion plan), else how it will be. A picture not made yet is only
  // set to be made the other way (Generate makes it); a made one asks first, and the yes makes it
  // again that way.
  const madeAs: Level = state === "planned" ? unit.level : p.level || (p.motion ? "rich" : "simple");
  const level = (next: Level) => {
    if (next === madeAs) return setToLevel(null);
    if (state === "planned") return void run(() => api.chooseEpisode(view.id, { units: { [unit.id]: { level: next } } }));
    setToLevel(next);
  };
  const remake = (to: Level) => {
    setToLevel(null);
    setSent(to);
    void run(() => api.makePictures(view.id, { units: [unit.id], level: to })).then(() => setSent(null));
  };
  return (
    <>
      <div className="ep-figure-top">
        <div className="ep-figure-shot">
          {moving && preview ? (
            <video className="ep-figure-pic" src={preview.url} autoPlay controls playsInline
              onEnded={() => setPreview(null)} onError={() => {setPreview(null); setPlayError("This preview could not be played.");}} />
          ) : <button
            type="button"
            className="ep-figure-pic"
            data-empty={!still || undefined}
            data-working={(designed && state === "making") || undefined}
            aria-label={`Open the ${name.toLowerCase()} with its choices`}
            onClick={onOpen}
          >
            {still ? (
              <img src={still.url} alt="" loading="lazy" />
            ) : (
              <KindArt kind={unit.kind_of_picture} />
            )}
          </button>}
          {playError && <small role="alert">{playError}</small>}
          {preparing && <small role="status">Preparing playback…</small>}
          {clip && !moving && (
            <button type="button" className="ep-figure-play" disabled={preparing} aria-label={`${moving ? "Stop" : "Play"} the ${name.toLowerCase()}`} aria-pressed={moving} onClick={play}>
              {moving ? <Square /> : <Play />}
            </button>
          )}
        </div>
        <div className="ep-figure-meta">
          <header className="ep-block-head" data-status={state}>
            <KindIcon block={block} />
            <b>{name}</b>
            {pictureWords(unit, view) !== "Made" && <span>{pictureWords(unit, view)}</span>}
            {tools}
            {designed && (
              <div ref={levelAnchor} className="ep-figure-level">
                <SegmentedControl<Level>
                  size="sm"
                  aria-label={`How the ${name.toLowerCase()} is made`}
                  value={toLevel ?? sent ?? madeAs}
                  disabled={busy || state === "making" || Boolean(sent)}
                  onChange={level}
                  options={[
                    { value: "simple", label: LEVEL_NAMES.simple },
                    { value: "rich", label: LEVEL_NAMES.rich },
                  ]}
                />
              </div>
            )}
          </header>
          <div className="ep-beat-options">
            {designed && <GenerationSettings view={view} unit={unit} run={run} busy={busy || state === "making"} />}
            {p.motion && <MotionPlan motion={p.motion} lines={lines} />}
          </div>
          {unit.shows && <p className="ep-block-shows">{unit.shows}</p>}
          <Popover open={Boolean(toLevel)} anchor={levelAnchor} onClose={() => setToLevel(null)}
            side="bottom" align="end" width={296} title={toLevel === "rich" ? "Make it as motion graphics?" : "Make it simple?"}>
            {toLevel && <div className="ep-level-confirm">
              <ol className="ep-level-steps" aria-label="What happens, in order">
                {BUILD[toLevel].map((s) => (
                  <li key={s.id} data-yours={s.yours || undefined}>
                    {s.label}
                  </li>
                ))}
              </ol>
              <span>{levelCost(unit, toLevel)}</span>
              <div className="ep-level-do">
                <button type="button" className="btn" onClick={() => setToLevel(null)}>
                  Cancel
                </button>
                <button type="button" className="btn primary" disabled={busy} onClick={() => remake(toLevel)}>
                  Start
                </button>
              </div>
            </div>}
          </Popover>
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
                {unit.level === "simple" && unit.suggest === "rich" ? " Motion graphics are suggested for this one." : ""}
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
            <div className="ep-figure-build">
              {/* the build stage by stage, its builder's steps under the one it is on */}
              <PictureTrail unit={unit} builder={WRITERS[p.builder || unit.builder] ?? unit.builder} />
              <button type="button" className="btn" onClick={() => void api.stopEpisode(view.id, unit.id).catch(() => undefined)}>
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
            </div>
          ) : null}
        </div>
      </div>
      {(state === "go" || state === "made") && <Stills view={view} unit={unit} lines={lines} picked={picked} onPick={onPick} run={run} busy={busy} onPlay={play} playing={moving} />}
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
      <button ref={button} type="button" className="btn ep-beat-trigger" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
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

// Motion graphics' stills, one for the end of each of their lines, waiting for the person's go.
// The picture is built and moving by then, so where it can be played they play it; they give the
// go, or say what should change. The go makes nothing more: it puts the picture in the film as
// built, and says so where the stills were until the picture is made again.
export function Stills({
  view,
  unit,
  lines,
  picked,
  onPick,
  run,
  busy,
  onPlay,
  playing,
}: {
  view: EpisodeView;
  unit: EpisodeUnit;
  lines: EpisodeFrame[];
  picked: string;
  onPick: (frame: string) => void;
  run: Run;
  busy: boolean;
  // plays the picture where it is shown (its clip, once rendered), and whether it plays
  onPlay?: () => void;
  playing?: boolean;
}) {
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  const [went, setWent] = useState(false);
  const p = unit.picture;
  const gone = went && p.status === "made";
  useEffect(() => {
    if (p.status !== "made") setWent(false);
  }, [p.status]);
  const builder = WRITERS[p.builder || unit.builder] ?? unit.builder;
  const playIt = onPlay && (
    <button type="button" className="btn" aria-pressed={playing} disabled={!p.clip} title={p.clip ? undefined : "Its clip is still rendering"} onClick={onPlay}>
      {playing ? <Square /> : <Play />}
      {playing ? "Stop" : "Play it"}
    </button>
  );
  if (gone)
    return (
      <div className="ep-stills" data-went="">
        <div className="ep-stills-act">
          <Check aria-hidden="true" />
          <span role="status">Given the go: it's in the film. It was built before its stills, so nothing more is made.</span>
          {playIt}
        </div>
      </div>
    );
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
          <span>{builder.slice(0, 1).toUpperCase() + builder.slice(1)} built it. Play it and check where each line ends: your go puts it in the film.</span>
          {playIt}
          <button type="button" className="btn" disabled={busy} onClick={() => setNoting(true)}>
            Send a note
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={() =>
              void run(() => api.pictureGo(view.id, unit.id)).then((taken) => {
                if (taken) setWent(true);
              })
            }
          >
            Give the go
          </button>
        </div>
      )}
    </div>
  );
}
