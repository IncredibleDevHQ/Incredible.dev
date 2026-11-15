// An episode's studio, over the channel: the plan and the studio in one place. The bar holds the
// film, each chapter as a numbered dot and the one thing to do next. The film's page is the
// chapters beside the film so far, with the look, the voice and the pictures' level as three
// rows. A chapter is three columns and nothing else: its script, the frame for the line that is
// picked, and that line's choices. Recording happens in the same screen.
import { ArrowLeft, ArrowRight, ChevronLeft, ChevronRight, Circle, Clapperboard, Play, RotateCcw, Square, Upload, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type EpisodeChapter, type EpisodeChoices, type EpisodeFrame, type EpisodeUnit, type EpisodeView, type Level, type Presence, type WriterId } from "../../api";
import {
  allLines,
  chapterName,
  chapterState,
  clockLine,
  LAYOUTS,
  linesIn,
  linesOf,
  LOOKS,
  mmss,
  pictureCount,
  PICTURES,
  pictureWords,
  PRESENCE,
  redrawnBy,
  STATE_WORDS,
  takeOf,
  TRANSITIONS,
  unitOf,
} from "../../episode";
import { useHouse } from "../../store";
import { AgentMark } from "../../ui";
import { ProgressTracker } from "../ProgressTracker";
import { useRecorder, type Recording } from "./recorder";
import { LayoutThumb, Stage, type Playing } from "./Stage";

const FILM = "film";
const WRITERS: Record<string, string> = { claude: "Claude Code", codex: "Codex", kimi: "Kimi Code", builtin: "the built-in agent", demo: "the demo's writer" };
const PRESENCES: Presence[] = ["person", "both", "content"];

export function EpisodeStudio() {
  const view = useHouse((s) => s.episode);
  const openEpisode = useHouse((s) => s.openEpisode);
  const [at, setAt] = useState<string>(FILM);
  const [busy, setBusy] = useState(false);

  // Every change goes to the server and comes back as the whole episode.
  const run = useCallback(async (call: () => Promise<EpisodeView>) => {
    setBusy(true);
    try {
      useHouse.getState().setEpisode(await call());
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !(e.target as HTMLElement).closest("textarea, input, [data-recording]")) void openEpisode(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openEpisode]);

  if (!view) {
    return (
      <div className="ep" role="dialog" aria-modal="true" aria-label="Episode">
        <div className="ep-wait">
          <span className="spin" />
        </div>
      </div>
    );
  }
  const plan = view.plan;
  const chapter = plan?.chapters.find((c) => c.id === at);
  const ready = plan !== null && view.status !== "planning" && view.status !== "failed";
  return (
    <div className="ep" role="dialog" aria-modal="true" aria-label={`Episode: ${view.title}`}>
      <Bar view={view} at={chapter ? chapter.id : FILM} onAt={setAt} onClose={() => void openEpisode(null)} />
      {!ready || !plan ? (
        <Planning view={view} run={run} busy={busy} />
      ) : chapter ? (
        <Chapter key={chapter.id} view={view} chapter={chapter} run={run} busy={busy} onAt={setAt} />
      ) : (
        <FilmPage view={view} run={run} busy={busy} onAt={setAt} />
      )}
    </div>
  );
}

type Run = (call: () => Promise<EpisodeView>) => Promise<void>;

// The film, the chapters as dots, and nothing else: each page puts its own next step below.
function Bar({ view, at, onAt, onClose }: { view: EpisodeView; at: string; onAt: (at: string) => void; onClose: () => void }) {
  const chapters = view.status === "planning" || view.status === "failed" ? [] : (view.plan?.chapters ?? []);
  return (
    <header className="ep-bar">
      <button type="button" className="icon-btn" aria-label="Back to the canvas" title="Back to the canvas" onClick={onClose}>
        <ArrowLeft />
      </button>
      <h2>{view.title}</h2>
      {chapters.length > 0 && (
        <nav className="ep-dots" aria-label="The film and its chapters">
          <button type="button" className="ep-film-pill" aria-current={at === FILM || undefined} onClick={() => onAt(FILM)}>
            <Clapperboard />
            Film
          </button>
          {chapters.map((c, i) => {
            const state = view.approved ? chapterState(view, c) : "ready";
            return (
              <button
                type="button"
                key={c.id}
                className="ep-dot"
                data-state={state}
                aria-current={at === c.id || undefined}
                aria-label={`Chapter ${i + 1}, ${chapterName(c)}, ${view.approved ? STATE_WORDS[state] : "planned"}`}
                title={`${chapterName(c)} · ${view.approved ? STATE_WORDS[state] : "planned"}`}
                disabled={!view.approved}
                onClick={() => onAt(c.id)}
              >
                <b>{i + 1}</b>
                {at === c.id && <span>{chapterName(c)}</span>}
              </button>
            );
          })}
        </nav>
      )}
      <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
        <X />
      </button>
    </header>
  );
}

// While the plan is being written: where the writer is, and what it has put down so far.
function Planning({ view, run, busy }: { view: EpisodeView; run: Run; busy: boolean }) {
  const stage = view.stage;
  const failed = view.status === "failed";
  const current = stage.name === "done" ? "done" : stage.name === "redo" || stage.name === "fix" ? "frames" : (stage.name ?? "brief");
  const writers = view.options.writers.filter((w) => w.ready);
  const [writer, setWriter] = useState<WriterId>(view.writer);
  return (
    <main className="ep-plan">
      <section className="ep-plan-main">
        <p className="ep-kicker">{failed ? "The plan stopped" : `Planning with ${WRITERS[view.writer] ?? "an agent"}`}</p>
        <h1>{view.written.idea || view.title}</h1>
        <ProgressTracker steps={view.steps} current={current} failed={failed} />
        {failed ? (
          <div className="ep-plan-fail">
            <p>{stage.said || "The writer stopped before the plan was done."}</p>
            <div className="ep-row">
              <WriterPick writers={writers} value={writer} onChange={setWriter} />
              <button type="button" className="btn primary" disabled={busy} onClick={() => void run(() => api.planAgain(view.id, writer === view.writer ? "" : writer))}>
                <RotateCcw />
                Pick it up
              </button>
            </div>
            <p className="faint">It carries on from the stage it stopped at. Another agent picks up the same files and the record of what was said.</p>
          </div>
        ) : (
          <div className="ep-row">
            <p className="ep-said" aria-live="polite">
              <span className="spin" />
              {stage.state === "reading" ? "Reading and checking what was written" : stage.said || "Working"}
              {(stage.round ?? 0) > 0 && <span className="faint"> · fix {stage.round}</span>}
            </p>
            <button type="button" className="btn" onClick={() => void api.stopEpisode(view.id).catch((e: Error) => useHouse.getState().say(e.message))}>
              <Square />
              Stop
            </button>
          </div>
        )}
      </section>
      {view.written.chapters.length > 0 && (
        <section className="ep-plan-so-far" aria-label="Written so far">
          <h3>Chapters so far</h3>
          <ol>
            {view.written.chapters.map((c) => (
              <li key={c.id}>
                <span>{c.question}</span>
                <small>{c.beats} lines</small>
              </li>
            ))}
          </ol>
        </section>
      )}
    </main>
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

// The film: its chapters on the left with the one next step, the film so far on the right with
// the three things chosen once for all of it.
function FilmPage({ view, run, busy, onAt }: { view: EpisodeView; run: Run; busy: boolean; onAt: (at: string) => void }) {
  const plan = view.plan!;
  const [hover, setHover] = useState(plan.chapters[0].id);
  const shown = plan.chapters.find((c) => c.id === hover) ?? plan.chapters[0];
  const frame = linesOf(shown)[0];
  const film = view.film_state;
  const next = plan.chapters.find((c) => chapterState(view, c) !== "recorded");
  const recorded = plan.chapters.filter((c) => takeOf(view, c.id)).length;
  const set = (settings: EpisodeChoices["settings"]) => run(() => api.chooseEpisode(view.id, { settings }));
  const presenterOff = view.settings.presenter === "off";
  const pictures = pictureCount(view);
  // A look the person asked for that would redraw pictures already made: it waits for a yes.
  const [asked, setAsked] = useState<string | null>(null);
  const look = (id: string) => {
    if (id === view.settings.theme) return;
    if (view.approved && pictures.all > 0) setAsked(id);
    else void set({ theme: id });
  };
  return (
    <main className="ep-film">
      <section className="ep-film-left">
        <p className="ep-kicker">{view.approved ? `${recorded} of ${plan.chapters.length} chapters recorded` : "Approve once, then go chapter by chapter"}</p>
        <h1>{plan.brief.idea || view.title}</h1>
        <ol className="ep-chapters">
          {plan.chapters.map((c, i) => {
            const state = chapterState(view, c);
            return (
              <li key={c.id}>
                <button type="button" disabled={!view.approved} onMouseEnter={() => setHover(c.id)} onFocus={() => setHover(c.id)} onClick={() => onAt(c.id)}>
                  <b className="ep-num" data-state={view.approved ? state : "ready"}>
                    {i + 1}
                  </b>
                  <span>
                    <strong>{c.question}</strong>
                    <small>
                      {chapterName(c)} · {mmss(view.clock?.chapters.find((x) => x.id === c.id)?.seconds ?? c.seconds)}
                      {view.approved && ` · ${STATE_WORDS[state]}`}
                    </small>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
        {view.approved && pictures.making > 0 && (
          <div className="ep-row">
            <p className="ep-said" aria-live="polite">
              <span className="spin" />
              {pictures.made} of {pictures.all} pictures made
            </p>
            <button type="button" className="btn" onClick={() => void api.stopEpisode(view.id).catch((e: Error) => useHouse.getState().say(e.message))}>
              <Square />
              Stop
            </button>
          </div>
        )}
        {view.approved && pictures.making === 0 && pictures.stopped > 0 && (
          <div className="ep-row">
            <p className="ep-said">
              {pictures.stopped} {pictures.stopped === 1 ? "picture" : "pictures"} not made
            </p>
            <button type="button" className="btn" disabled={busy} onClick={() => void run(() => api.makePictures(view.id))}>
              <RotateCcw />
              {pictures.stopped === 1 ? "Make it" : "Make them"}
            </button>
          </div>
        )}
        {!view.approved ? (
          <button type="button" className="btn primary ep-next" disabled={busy} onClick={() => void run(() => api.approveEpisode(view.id))}>
            Approve the plan
            <ArrowRight />
          </button>
        ) : next ? (
          <button type="button" className="btn primary ep-next" onClick={() => onAt(next.id)}>
            Open chapter {plan.chapters.indexOf(next) + 1}
            <ArrowRight />
          </button>
        ) : null}
        {view.checks.length > 0 && (
          <details className="ep-more">
            <summary>
              {view.checks.length} {view.checks.length === 1 ? "thing" : "things"} the checks flag
            </summary>
            <ul className="ep-checks">
              {view.checks.map((c, i) => (
                <li key={i} data-level={c.level}>
                  <b>{c.where}</b> {c.text}
                </li>
              ))}
            </ul>
          </details>
        )}
        <details className="ep-more">
          <summary>
            Written by {WRITERS[view.writer] ?? "an agent"} · {view.runs.length} {view.runs.length === 1 ? "turn" : "turns"}
          </summary>
          <ul className="ep-runs">
            {view.runs.map((r) => (
              <li key={r.id}>
                <b>{r.lane === "plan" ? "Plan" : "Picture"}</b>
                <span>{r.said || r.asked}</span>
                <small>
                  {WRITERS[r.harness] ?? r.harness} · {r.steps} steps{r.state !== "done" ? ` · ${r.state}` : ""}
                </small>
              </li>
            ))}
          </ul>
        </details>
      </section>
      <section className="ep-film-right">
        {film.status === "done" && film.file ? (
          <video className="ep-film-video" src={film.file.url} controls preload="metadata" />
        ) : (
          <Stage view={view} frame={frame} unit={unitOf(view, frame.id)} take={takeOf(view, shown.id)} />
        )}
        <div className="ep-film-row">
          <span className="ep-film-len">
            {plan.chapters.length} chapters · {mmss(view.clock?.total ?? plan.totals.seconds)}
          </span>
          <span className="ep-film-note" data-tone={film.status === "failed" ? "red" : film.stale ? "amber" : undefined}>
            {film.status === "rendering"
              ? `Rendering · ${Math.round((film.fraction ?? 0) * 100)}%`
              : film.status === "failed"
                ? film.failure || "The render stopped."
                : film.status === "done"
                  ? film.stale
                    ? "Changed since it was rendered"
                    : "Rendered"
                  : view.approved && recorded < plan.chapters.length
                    ? "A draft shows a stand-in where you haven't recorded"
                    : ""}
          </span>
          {view.approved && (
            <button
              type="button"
              className={`btn ${recorded === plan.chapters.length && (film.status !== "done" || film.stale) ? "primary" : ""}`}
              disabled={busy || film.status === "rendering"}
              onClick={() => void run(() => api.renderEpisode(view.id))}
            >
              <Clapperboard />
              {film.status === "rendering" ? "Rendering" : film.status === "done" ? "Render again" : recorded === plan.chapters.length ? "Render the film" : "Render a draft"}
            </button>
          )}
        </div>
        <dl className="ep-settings">
          <div>
            <dt>Look</dt>
            <dd>
              <span className="ep-looks">
                {view.options.themes
                  .filter((t) => (t.presenter === "off") === presenterOff)
                  .map((t) => (
                    <button type="button" key={t.id} aria-pressed={view.settings.theme === t.id} disabled={busy} title={t.stage} onClick={() => look(t.id)}>
                      {LOOKS[t.id] ?? t.name}
                    </button>
                  ))}
              </span>
              {asked && (
                <p
                  className="ep-confirm"
                  role="alertdialog"
                  aria-label={`Change the look to ${LOOKS[asked] ?? asked}`}
                  onKeyDown={(e) => {
                    if (e.key !== "Escape") return;
                    e.stopPropagation();
                    setAsked(null);
                  }}
                >
                  <span>
                    {LOOKS[asked] ?? asked} redraws all {pictures.all} pictures.
                  </span>
                  <button
                    type="button"
                    className="btn primary"
                    autoFocus
                    disabled={busy}
                    onClick={() => {
                      setAsked(null);
                      void set({ theme: asked });
                    }}
                  >
                    Change the look
                  </button>
                  <button type="button" className="btn" onClick={() => setAsked(null)}>
                    Cancel
                  </button>
                </p>
              )}
            </dd>
          </div>
          <div>
            <dt>Voice</dt>
            <dd>
              <Seg
                label="Voice"
                value={view.settings.voice}
                options={[
                  ["live", presenterOff ? "Recorded" : "Your voice"],
                  ["narrator", "Narrator"],
                ]}
                off={view.options.narrator ? [] : ["narrator"]}
                offWhy="Narration needs ELEVENLABS_API_KEY and DESIGN_AGENT_NARRATOR_VOICE_ID"
                disabled={busy}
                onChange={(voice) => void set({ voice })}
              />
            </dd>
          </div>
          <div>
            <dt>Pictures</dt>
            <dd>
              <Seg
                label="Pictures"
                value={view.settings.level}
                options={[
                  ["simple", "Simple"],
                  ["rich", "Rich"],
                ]}
                disabled={busy}
                onChange={(level) => void set({ level })}
              />
              <small>{view.settings.level === "rich" ? "Posed as stills for your go before they count" : "Made at once from the plan"}</small>
            </dd>
          </div>
        </dl>
      </section>
    </main>
  );
}

function Seg<T extends string>({
  label,
  value,
  options,
  off = [],
  offWhy,
  disabled,
  onChange,
}: {
  label: string;
  value: T;
  options: [T, string][];
  off?: T[];
  offWhy?: string;
  disabled?: boolean;
  onChange: (value: T) => void;
}) {
  return (
    <span className="ep-seg" role="radiogroup" aria-label={label}>
      {options.map(([id, name]) => (
        <button
          type="button"
          role="radio"
          key={id}
          aria-checked={value === id}
          disabled={disabled || off.includes(id)}
          title={off.includes(id) ? offWhy : undefined}
          onClick={() => value !== id && onChange(id)}
        >
          {name}
        </button>
      ))}
    </span>
  );
}

// One chapter: the script, the frame for the picked line, that line's choices.
function Chapter({ view, chapter, run, busy, onAt }: { view: EpisodeView; chapter: EpisodeChapter; run: Run; busy: boolean; onAt: (at: string) => void }) {
  const plan = view.plan!;
  const lines = useMemo(() => linesOf(chapter), [chapter]);
  const number = plan.chapters.indexOf(chapter) + 1;
  const [picked, setPicked] = useState(lines[0].id);
  const [playing, setPlaying] = useState<Playing>(null);
  const upload = useRef<HTMLInputElement>(null);
  const take = takeOf(view, chapter.id);
  const presenterOff = view.settings.presenter === "off";

  const save = useCallback(
    async (recording: Recording) => {
      await run(() => api.addTake(view.id, { chapter: chapter.id, marks: recording.marks, file: recording.blob, name: recording.name }));
    },
    [run, view.id, chapter.id],
  );
  const frames = useMemo(() => lines.map((l) => l.id), [lines]);
  const recorder = useRecorder({ frames, camera: !presenterOff, onDone: save });
  const recording = recorder.state !== "off";
  const line = recording && recorder.state !== "saving" ? lines[recorder.index] : (lines.find((l) => l.id === picked) ?? lines[0]);
  const unit = unitOf(view, line.id);
  const at = lines.indexOf(line);
  const state = chapterState(view, chapter);
  const following = plan.chapters[number];

  // Space or the right arrow starts the next line while recording.
  useEffect(() => {
    if (recorder.state !== "recording") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === " " || e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        recorder.next();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [recorder]);

  const play = () => {
    const clock = clockLine(view, line.id);
    if (take && clock?.source.kind === "take") {
      const from = clock.source.offset ?? 0;
      return setPlaying({ of: "take", from, to: from + clock.seconds });
    }
    if (unit?.picture.clip) {
      const first = lines.find((l) => l.id === unit.frames[0]) ?? plan.chapters.flatMap(linesOf).find((l) => l.id === unit.frames[0]);
      const from = Math.max(0, line.start - (first?.start ?? line.start));
      setPlaying({ of: "clip", from, to: from + line.seconds });
    }
  };
  const canPlay = Boolean((take && clockLine(view, line.id)?.source.kind === "take") || unit?.picture.clip);
  const pick = (frame: string) => {
    setPlaying(null);
    setPicked(frame);
  };

  return (
    <main className="ep-chapter" data-recording={recording || undefined}>
      <section className="ep-script" aria-label="Script">
        <header>
          <b>Chapter {number}</b>
          <span>
            {chapterName(chapter)} · {mmss(view.clock?.chapters.find((c) => c.id === chapter.id)?.seconds ?? chapter.seconds)}
          </span>
        </header>
        <ol>
          {lines.map((l, i) => {
            const mine = unitOf(view, l.id);
            const leads = mine && mine.frames[0] === l.id;
            return (
              <li key={l.id}>
                {leads && (
                  <p className="ep-unit" data-status={mine.kind === "undesigned" ? "making" : mine.picture.status}>
                    {PICTURES[mine.kind_of_picture] ?? "Picture"} · {mine.level === "rich" ? "Rich" : "Simple"} · {pictureWords(mine)}
                  </p>
                )}
                <button type="button" className="ep-line" aria-current={l.id === line.id || undefined} disabled={recording} onClick={() => pick(l.id)}>
                  <i className="ep-who" data-presence={l.presence} aria-label={PRESENCE[l.presence]} />
                  <span>{l.vo}</span>
                  {take && !recording && <small aria-label="Recorded">✓</small>}
                  {recording && i < recorder.index && <small>✓</small>}
                </button>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="ep-middle">
        <div className="ep-stage-wrap">
          <Stage view={view} frame={line} unit={unit} take={recording ? undefined : take} stream={recorder.stream} playing={playing} onEnded={() => setPlaying(null)} />
          {recorder.state === "count" && <span className="ep-count">{recorder.count}</span>}
        </div>
        {recording ? (
          <div className="ep-recbar" data-recording>
            {recorder.state === "asking" && <span className="ep-said"><span className="spin" />Waiting for the camera and microphone</span>}
            {recorder.state === "ready" && (
              <>
                <button type="button" className="btn primary" onClick={recorder.start}>
                  <Circle />
                  Start recording
                </button>
                <span className="faint">One take for the chapter. Press Space at the end of each line.</span>
              </>
            )}
            {recorder.state === "count" && <span className="ep-said">Get ready</span>}
            {recorder.state === "recording" && (
              <>
                <span className="ep-live-dot" />
                <b className="ep-timer">{mmss(recorder.elapsed)}</b>
                <button type="button" className="btn primary" onClick={recorder.next}>
                  {recorder.index + 1 >= lines.length ? "Finish" : "Next line"}
                  <kbd>Space</kbd>
                </button>
              </>
            )}
            {recorder.state === "saving" && <span className="ep-said"><span className="spin" />Saving the take</span>}
            {recorder.state !== "saving" && (
              <button type="button" className="btn" onClick={() => recorder.stop(false)}>
                Cancel
              </button>
            )}
          </div>
        ) : (
          <div className="ep-controls">
            <button type="button" className="icon-btn" aria-label="Previous line" disabled={at === 0} onClick={() => pick(lines[at - 1].id)}>
              <ChevronLeft />
            </button>
            <span className="ep-pos">
              Line {at + 1} of {lines.length}
            </span>
            <button type="button" className="icon-btn" aria-label="Next line" disabled={at === lines.length - 1} onClick={() => pick(lines[at + 1].id)}>
              <ChevronRight />
            </button>
            <button type="button" className="btn" disabled={!canPlay} onClick={() => (playing ? setPlaying(null) : play())}>
              {playing ? <Square /> : <Play />}
              {playing ? "Stop" : "Play"}
            </button>
            <span className="ep-gap" />
            {take && (
              <span className="faint">
                Take {take.n} · {mmss(take.seconds)}
              </span>
            )}
            {take ? (
              <button type="button" className="icon-btn" aria-label="Bring a recording instead" title="Bring a recording instead: a video or audio file of this chapter" disabled={busy} onClick={() => upload.current?.click()}>
                <Upload />
              </button>
            ) : (
              <button type="button" className="btn" title="A video or audio file of this chapter" disabled={busy} onClick={() => upload.current?.click()}>
                <Upload />
                Bring a recording
              </button>
            )}
            <button type="button" className={`btn ${take ? "" : "primary"}`} disabled={busy} onClick={() => void recorder.arm()}>
              <Circle />
              {take ? "Retake" : `Record chapter ${number}`}
            </button>
            {take &&
              (following ? (
                <button type="button" className="btn primary" onClick={() => onAt(following.id)}>
                  Chapter {number + 1}
                  <ArrowRight />
                </button>
              ) : (
                <button type="button" className="btn primary" onClick={() => onAt(FILM)}>
                  The film
                  <ArrowRight />
                </button>
              ))}
            <input
              ref={upload}
              type="file"
              accept="video/*,audio/*"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void run(() => api.addTake(view.id, { chapter: chapter.id, marks: [], file, name: file.name }));
              }}
            />
          </div>
        )}
        {recorder.problem && (
          <p className="ep-notice" data-tone="red" role="alert">
            {recorder.problem}
          </p>
        )}
        {!recording && unit && <Stills view={view} unit={unit} lines={lines} picked={line.id} onPick={pick} run={run} busy={busy} />}
        {!recording && !take && state === "making" && <p className="ep-notice">You can record now. The pictures are finished meanwhile and timed to your take.</p>}
      </section>

      {recording ? (
        <section className="ep-say" aria-label="Say it" aria-live="polite">
          <p className="ep-kicker">
            Say it · line {Math.min(recorder.index + 1, lines.length)} of {lines.length}
          </p>
          <p className="ep-say-now">{line.vo}</p>
          {lines[recorder.index + 1] && <p className="ep-say-next">{lines[recorder.index + 1].vo}</p>}
        </section>
      ) : (
        <Choices view={view} chapter={chapter} line={line} unit={unit} run={run} busy={busy} onFilm={() => onAt(FILM)} />
      )}
    </main>
  );
}

// A rich picture's stills, one per line, for the person's go or a note.
function Stills({
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
  if (p.status === "failed") {
    return (
      <p className="ep-notice" data-tone="red">
        This picture couldn't be built: {p.failure || "it stopped"}.{" "}
        <button type="button" className="linkish" disabled={busy} onClick={() => void run(() => api.pictureNote(view.id, unit.id, "Build it again."))}>
          Try again
        </button>
      </p>
    );
  }
  if (p.status !== "go") return null;
  const mine = lines.filter((l) => unit.frames.includes(l.id));
  const send = () => {
    if (!note.trim()) return;
    void run(() => api.pictureNote(view.id, unit.id, note.trim())).then(() => {
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

// The picked line's choices: who has the frame, the layout, the picture.
function Choices({
  view,
  chapter,
  line,
  unit,
  run,
  busy,
  onFilm,
}: {
  view: EpisodeView;
  chapter: EpisodeChapter;
  line: EpisodeFrame;
  unit?: EpisodeUnit;
  run: Run;
  busy: boolean;
  onFilm: () => void;
}) {
  const presenterOff = view.settings.presenter === "off";
  const theme = view.options.themes.find((t) => t.id === view.settings.theme);
  const layouts = (line.options ?? []).filter((o) => o.presence === line.presence).map((o) => o.layout);
  const kit = layouts.includes(line.layout) ? layouts : [line.layout, ...layouts];
  const choose = (body: EpisodeChoices) => run(() => api.chooseEpisode(view.id, body));
  const setPresence = (presence: Presence) => choose({ frames: { [line.id]: { presence } } });
  const setLayout = (layout: string) => choose({ frames: { [line.id]: { layout } } });
  const setLevel = (level: Level) => unit && choose({ units: { [unit.id]: { level } } });

  // A layout used for the chapter or the film reaches every line of this presence there. It is
  // asked first when it would redraw more than one picture.
  const scope = line.override?.scope;
  const [wide, setWide] = useState<{ film: boolean; redraws: number } | null>(null);
  useEffect(() => setWide(null), [line.id, line.layout]);
  const applyFor = (film: boolean) => {
    const set = { layouts: { [line.presence]: line.layout } };
    const unset = { layouts: { [line.presence]: null } };
    return choose({
      // the line's own layout, and its chapter's when the film takes over, give way to it
      frames: { [line.id]: { layout: null } },
      chapters: { [chapter.id]: film ? unset : set },
      ...(film ? { all: set } : {}),
    });
  };
  const askFor = (film: boolean) => {
    const redraws = redrawnBy(view, line.presence, line.layout, film ? undefined : chapter.id);
    if (redraws > 1) setWide({ film, redraws });
    else void applyFor(film);
  };
  const undo = () =>
    scope === "film"
      ? choose({ all: { layouts: { [line.presence]: null } } })
      : scope === "chapter"
        ? choose({ chapters: { [chapter.id]: { layouts: { [line.presence]: null } } } })
        : choose({ frames: { [line.id]: { presence: null, layout: null } } });
  const reach = scope ? linesIn(view, line.presence, scope === "chapter" ? chapter.id : undefined).filter((x) => x.line.layout === line.layout).length : 0;

  // The picture this line shows is drawn once, on the line that brings it in: its type, where
  // it sits and how it comes in are picked there, whichever of its lines is open.
  const lead = unit ? allLines(view).find((x) => x.line.id === unit.frames[0])?.line : undefined;
  const drawn = unit?.kind === "picture" && lead;
  const setPlace = (presence: Presence) => unit && choose({ frames: Object.fromEntries(unit.frames.map((id) => [id, { presence }])) });
  const planMove = line.transition && line.transition !== "none" ? line.transition : "cut";
  const move = line.picked?.transition ?? planMove;
  const bringsIn = drawn && lead.id === line.id && line.presence !== "person";
  return (
    <aside className="ep-choices" aria-label="Choices for this line">
      <section>
        <h3>Who has the frame</h3>
        <span className="ep-seg wide" role="radiogroup" aria-label="Who has the frame">
          {PRESENCES.map((p) => (
            <button type="button" role="radio" key={p} aria-checked={line.presence === p} disabled={busy || presenterOff} onClick={() => line.presence !== p && void setPresence(p)}>
              <i className="ep-who" data-presence={p} />
              {PRESENCE[p]}
            </button>
          ))}
        </span>
        {presenterOff && <small>Nobody is on screen in this film.</small>}
      </section>
      <section>
        <h3>
          Layout <span>{LAYOUTS[line.layout] ?? line.layout}</span>
        </h3>
        <div className="ep-layouts" role="radiogroup" aria-label="Layout">
          {kit.map((id) => (
            <button type="button" role="radio" key={id} aria-checked={line.layout === id} aria-label={LAYOUTS[id] ?? id} title={LAYOUTS[id] ?? id} disabled={busy} onClick={() => line.layout !== id && void setLayout(id)}>
              <LayoutThumb view={view} layout={id} />
            </button>
          ))}
        </div>
        {line.override && !wide && (
          <p className="ep-picked">
            <span>{scope ? `Set for the ${scope} · ${reach} ${reach === 1 ? "line" : "lines"}` : "Your pick"}</span>
            {scope !== "film" && (
              <span>
                Use it for{" "}
                {!scope && (
                  <>
                    <button type="button" className="linkish" disabled={busy} onClick={() => askFor(false)}>
                      the chapter
                    </button>{" or "}
                  </>
                )}
                <button type="button" className="linkish" disabled={busy} onClick={() => askFor(true)}>
                  the film
                </button>
              </span>
            )}
            <button type="button" className="linkish" disabled={busy} onClick={() => void undo()}>
              Undo
            </button>
          </p>
        )}
        {wide && (
          <p
            className="ep-confirm"
            role="alertdialog"
            aria-label={`Use ${LAYOUTS[line.layout] ?? line.layout} for the ${wide.film ? "film" : "chapter"}`}
            onKeyDown={(e) => {
              if (e.key !== "Escape") return;
              e.stopPropagation();
              setWide(null);
            }}
          >
            <span>
              {LAYOUTS[line.layout] ?? line.layout} for the {wide.film ? "film" : "chapter"} redraws {wide.redraws} pictures.
            </span>
            <button
              type="button"
              className="btn primary"
              autoFocus
              disabled={busy}
              onClick={() => {
                const film = wide.film;
                setWide(null);
                void applyFor(film);
              }}
            >
              Use it
            </button>
            <button type="button" className="btn" onClick={() => setWide(null)}>
              Cancel
            </button>
          </p>
        )}
      </section>
      <section>
        <h3>Picture</h3>
        {unit ? (
          <>
            <Seg
              label="How the picture is made"
              value={unit.level}
              options={[
                ["simple", "Simple"],
                ["rich", "Rich"],
              ]}
              disabled={busy || unit.kind === "undesigned"}
              onChange={(level) => void setLevel(level)}
            />
            {!presenterOff && lead && (
              <Seg<Presence>
                label="Where the picture sits"
                value={lead.presence}
                options={[
                  ["both", "Beside you"],
                  ["content", "Full screen"],
                ]}
                disabled={busy}
                onChange={(presence) => void setPlace(presence)}
              />
            )}
            <small>
              {unit.kind === "undesigned"
                ? "A picture is being planned for this line."
                : unit.level === "rich"
                  ? "Posed as stills for your go, then it counts as made."
                  : `Made at once from the plan.${unit.suggest === "rich" ? " Rich is suggested for this one." : ""}`}
            </small>
          </>
        ) : (
          <small>{line.presence === "person" ? "None. This line is said to camera." : "None for this line."}</small>
        )}
      </section>
      {(line.cues?.length || line.shows) && (
        <details className="ep-more">
          <summary>
            Motion <span>{line.cues?.length ? `${line.cues.length} ${line.cues.length === 1 ? "step" : "steps"}` : ""}</span>
          </summary>
          {line.shows && <p className="ep-shows">{line.shows}</p>}
          {line.cues && line.cues.length > 0 && (
            <ol className="ep-cues">
              {line.cues.map((c, i) => (
                <li key={i}>
                  <b>“{c.at}”</b> {c.does}
                </li>
              ))}
            </ol>
          )}
        </details>
      )}
      {bringsIn && (
        <details className="ep-more">
          <summary>
            Transition <span>{TRANSITIONS[move] ?? "Cut"}</span>
          </summary>
          <span className="ep-looks" role="group" aria-label="How the picture comes in">
            {view.options.transitions.map((id) => (
              <button type="button" key={id} aria-pressed={move === id} disabled={busy} onClick={() => move !== id && void choose({ frames: { [line.id]: { transition: id === planMove ? null : id } } })}>
                {TRANSITIONS[id] ?? id}
              </button>
            ))}
          </span>
          {line.picked?.transition && (
            <p className="ep-picked">
              <span>Your pick</span>
              <button type="button" className="linkish" disabled={busy} onClick={() => void choose({ frames: { [line.id]: { transition: null } } })}>
                Undo
              </button>
            </p>
          )}
        </details>
      )}
      {drawn && unit && (
        <details className="ep-more">
          <summary>
            Picture type <span>{PICTURES[unit.kind_of_picture] ?? "Picture"}</span>
          </summary>
          <span className="ep-looks" role="group" aria-label="What kind of picture it is">
            {view.options.pictures.map((id) => (
              <button
                type="button"
                key={id}
                aria-pressed={unit.kind_of_picture === id}
                disabled={busy}
                onClick={() => unit.kind_of_picture !== id && void choose({ frames: { [lead.id]: { picture: id === lead.picture ? null : id } } })}
              >
                {PICTURES[id] ?? id}
              </button>
            ))}
          </span>
          {lead.picked?.picture && (
            <p className="ep-picked">
              <span>Your pick</span>
              <button type="button" className="linkish" disabled={busy} onClick={() => void choose({ frames: { [lead.id]: { picture: null } } })}>
                Undo
              </button>
            </p>
          )}
        </details>
      )}
      <footer>
        <span>
          {LOOKS[theme?.id ?? ""] ?? "Look"} · {view.settings.voice === "narrator" ? "narrator" : "your voice"} · {view.settings.level}
        </span>
        <button type="button" className="linkish" onClick={onFilm}>
          Change
        </button>
      </footer>
    </aside>
  );
}
