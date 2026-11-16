// An episode's studio, over the channel: the plan and the studio in one place. The bar holds the
// film, each chapter as a numbered dot and the one thing to do next. The film's page is the
// chapters beside the film so far, with the look, the voice and the pictures' level as three
// rows. A chapter is three columns and nothing else: its script, the frame for the line that is
// picked, and that line's choices. Words are changed where they are read; anything else is
// asked for in the change bar under the script. Recording happens in the same screen.
import { ArrowLeft, ArrowRight, ChevronLeft, ChevronRight, Circle, Clapperboard, Mic, Pencil, Play, RotateCcw, Square, Undo2, Upload, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type EpisodeChapter, type EpisodeChoices, type EpisodeFrame, type EpisodeUnit, type EpisodeView, type WriterId } from "../../api";
import { chapterName, chapterState, clockLine, linesOf, LOOKS, mmss, pictureCount, PICTURES, pictureWords, PRESENCE, STATE_WORDS, takeOf, unitOf } from "../../episode";
import { useHouse } from "../../store";
import { AgentMark } from "../../ui";
import { FileDrop } from "../FileDrop";
import { Kbd } from "../Kbd";
import { ProgressTracker } from "../ProgressTracker";
import { SegmentedControl } from "../SegmentedControl";
import { Tooltip } from "../Tooltip";
import { Ask, Elapsed, turning, useWaiting, type AskHandle, type AskTarget, type Marks, type Run, type Waiting } from "./Ask";
import { Choices } from "./Choices";
import { Devices, Level } from "./Devices";
import { Changed } from "./Diff";
import { useRecorder, type Recording } from "./recorder";
import { LayoutThumb, Stage, type Playing } from "./Stage";
import { NarratorVoice } from "./Voice";

const FILM = "film";
const WRITERS: Record<string, string> = { claude: "Claude Code", codex: "Codex", kimi: "Kimi Code", builtin: "the built-in agent", demo: "the demo's writer" };

export function EpisodeStudio() {
  const view = useHouse((s) => s.episode);
  const openEpisode = useHouse((s) => s.openEpisode);
  const [at, setAt] = useState<string>(FILM);
  // The chapter that opens next is to be recorded at once: the run-through, once the choices are made.
  const [recordNext, setRecordNext] = useState(false);
  const [busy, setBusy] = useState(false);
  const go = useCallback((to: string, record = false) => {
    setRecordNext(record);
    setAt(to);
  }, []);

  // Every change goes to the server and comes back as the whole episode.
  const run = useCallback<Run>(async (call) => {
    setBusy(true);
    try {
      useHouse.getState().setEpisode(await call());
      return true;
    } catch (error) {
      useHouse.getState().say((error as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }, []);
  const waiting = useWaiting(view);
  // What the last change did is marked in the script when it lands here, and not for a change
  // that was already there when the studio opened. `quiet` is the change whose marks are off.
  const [quiet, setQuiet] = useState<number | null | "unseen">("unseen");
  const landed = view?.last_change?.at ?? null;
  if (view && quiet === "unseen") setQuiet(landed);
  const marks: Marks = { on: quiet !== "unseen" && landed !== null && landed !== quiet, set: (on) => setQuiet(on ? null : landed) };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !(e.target as HTMLElement).closest("textarea, input, [data-recording]")) void openEpisode(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openEpisode]);

  // Undo and its reverse on the keys every editor has them on, wherever the caret is not in a
  // field (there they are the field's own).
  useEffect(() => {
    if (!view) return;
    const onKey = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase();
      if (!(e.metaKey || e.ctrlKey) || e.altKey || (key !== "z" && key !== "y")) return;
      if ((e.target as HTMLElement).closest("textarea, input, [contenteditable]") || document.querySelector(".ep-chapter[data-recording]")) return;
      const back = key === "z" && !e.shiftKey;
      if (busy || turning(view) || !(back ? view.last_change : view.undone)) return;
      e.preventDefault();
      void run(() => (back ? api.undoEpisode(view.id) : api.redoEpisode(view.id)));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, busy, run]);

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
      <Bar view={view} ready={ready} at={chapter ? chapter.id : FILM} onAt={go} onClose={() => void openEpisode(null)} run={run} busy={busy} />
      {!ready || !plan ? (
        <Planning view={view} run={run} busy={busy} />
      ) : chapter ? (
        <Chapter
          key={chapter.id}
          view={view}
          chapter={chapter}
          run={run}
          busy={busy}
          record={recordNext}
          onAt={go}
          waiting={waiting}
          marks={marks}
        />
      ) : (
        <FilmPage view={view} run={run} busy={busy} onAt={go} waiting={waiting} />
      )}
    </div>
  );
}

// The film, the chapters as dots, and the one thing to do next. A chapter opens as soon as the
// plan is written, so it is read, and changed, before any picture is made.
function Bar({ view, ready, at, onAt, onClose, run, busy }: { view: EpisodeView; ready: boolean; at: string; onAt: (at: string) => void; onClose: () => void; run: Run; busy: boolean }) {
  const chapters = ready ? (view.plan?.chapters ?? []) : [];
  return (
    <header className="ep-bar">
      <Tooltip content="Back to the canvas" shortcut="Esc" side="bottom" align="start">
        <button type="button" className="icon-btn" aria-label="Back to the canvas" onClick={onClose}>
          <ArrowLeft />
        </button>
      </Tooltip>
      <h2>{view.title}</h2>
      {chapters.length > 0 && (
        <nav className="ep-dots" aria-label="The film and its chapters">
          <button type="button" className="ep-film-pill" aria-current={at === FILM || undefined} onClick={() => onAt(FILM)}>
            <Clapperboard />
            Film
          </button>
          {chapters.map((c, i) => {
            const state = view.approved ? chapterState(view, c) : "ready";
            const words = `${chapterName(c)} · ${view.approved ? STATE_WORDS[state] : "Planned"}`;
            return (
              <Tooltip key={c.id} content={words} side="bottom" disabled={at === c.id}>
                <button type="button" className="ep-dot" data-state={state} aria-current={at === c.id || undefined} aria-label={`Chapter ${i + 1}, ${words}`} onClick={() => onAt(c.id)}>
                  <b>{i + 1}</b>
                  {at === c.id && <span>{chapterName(c)}</span>}
                </button>
              </Tooltip>
            );
          })}
        </nav>
      )}
      {ready && <Now view={view} run={run} busy={busy} />}
      <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
        <X />
      </button>
    </header>
  );
}

// What happens next, said once and in one place: make the pictures, how far they are, or the
// ones that stopped.
function Now({ view, run, busy }: { view: EpisodeView; run: Run; busy: boolean }) {
  const pictures = pictureCount(view);
  if (!view.approved) {
    return (
      <div className="ep-now">
        <Tooltip content={`Draws the ${pictures.all} ${pictures.all === 1 ? "picture" : "pictures"} the plan has. Everything can still change after.`} side="bottom" align="end">
          <button type="button" className="btn primary" disabled={busy || turning(view)} onClick={() => void run(() => api.approveEpisode(view.id))}>
            Make the pictures
          </button>
        </Tooltip>
      </div>
    );
  }
  if (pictures.making > 0) {
    return (
      <div className="ep-now">
        <span className="ep-said" aria-live="polite">
          <span className="spin" />
          {pictures.made} of {pictures.all} pictures
        </span>
        <button type="button" className="btn" onClick={() => void api.stopEpisode(view.id).catch((e: Error) => useHouse.getState().say(e.message))}>
          <Square />
          Stop
        </button>
      </div>
    );
  }
  if (pictures.stopped > 0) {
    return (
      <div className="ep-now">
        <span className="ep-said">
          {pictures.stopped} {pictures.stopped === 1 ? "picture" : "pictures"} not made
        </span>
        <button type="button" className="btn" disabled={busy} onClick={() => void run(() => api.makePictures(view.id))}>
          <RotateCcw />
          {pictures.stopped === 1 ? "Make it" : "Make them"}
        </button>
      </div>
    );
  }
  return <div className="ep-now" />;
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
            {stage.at && <Elapsed since={stage.at} />}
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
function FilmPage({ view, run, busy, onAt, waiting }: { view: EpisodeView; run: Run; busy: boolean; onAt: (at: string) => void; waiting: Waiting }) {
  const plan = view.plan!;
  const [hover, setHover] = useState(plan.chapters[0].id);
  const shown = plan.chapters.find((c) => c.id === hover) ?? plan.chapters[0];
  const frame = linesOf(shown)[0];
  const film = view.film_state;
  const next = plan.chapters.find((c) => chapterState(view, c) !== "recorded") ?? plan.chapters[0];
  const recorded = plan.chapters.filter((c) => takeOf(view, c.id)).length;
  const set = (settings: EpisodeChoices["settings"]) => run(() => api.chooseEpisode(view.id, { settings }));
  const presenterOff = view.settings.presenter === "off";
  const pictures = pictureCount(view);
  // The length asked for is said only while the script is outside it: the checks decide that.
  const outside = Array.isArray(view.settings.seconds) && view.checks.some((c) => c.rule === "length") ? view.settings.seconds : null;
  // A look the person asked for that would redraw pictures already made: it waits for a yes.
  const [asked, setAsked] = useState<string | null>(null);
  const look = (id: string) => {
    if (id === view.settings.theme) return;
    if (view.approved && pictures.all > 0) setAsked(id);
    else void set({ theme: id });
  };
  const targets: AskTarget[] = [{ scope: "film", label: "The whole film", name: "The film", hint: "Ask for a change to the film", presets: ["Make it shorter", "A stronger opening", "Plainer words"] }];
  // Where the last change reached: its chapters are marked, so it is found without reading them all.
  const touched = useMemo(() => {
    const change = view.last_change;
    const lines = new Set([...(change?.lines ?? []), ...(change?.added ?? [])]);
    const cut = new Set((change?.cut ?? []).map((c) => c.chapter));
    return new Set(plan.chapters.filter((c) => cut.has(c.id) || linesOf(c).some((l) => lines.has(l.id))).map((c) => c.id));
  }, [view.last_change, plan.chapters]);
  return (
    <main className="ep-film">
      <section className="ep-film-left">
        <p className="ep-kicker">{view.approved ? `${recorded} of ${plan.chapters.length} chapters recorded` : "Read it and change what you like, then make the pictures"}</p>
        <h1>{plan.brief.idea || view.title}</h1>
        <ol className="ep-chapters">
          {plan.chapters.map((c, i) => {
            const state = chapterState(view, c);
            return (
              <li key={c.id}>
                <button type="button" onMouseEnter={() => setHover(c.id)} onFocus={() => setHover(c.id)} onClick={() => onAt(c.id)}>
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
                  {touched.has(c.id) && <em className="ep-touched">Changed</em>}
                </button>
              </li>
            );
          })}
        </ol>
        <Ask view={view} targets={targets} run={run} busy={busy} waiting={waiting} />
        <button type="button" className={`btn ep-next ${view.approved ? "primary" : ""}`} onClick={() => onAt(next.id)}>
          {view.approved ? "Open" : "Read"} chapter {plan.chapters.indexOf(next) + 1}
          <ArrowRight />
        </button>
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
            {outside && (
              <span className="ep-film-asked">
                {" "}
                · asked for {mmss(outside[0])} to {mmss(outside[1])}
              </span>
            )}
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
              <span className="ep-look-tiles">
                {view.options.themes
                  .filter((t) => (t.presenter === "off") === presenterOff)
                  .map((t) => {
                    // a look is known by the frame it is named for, which its kit lists first
                    const usual = t.kit[0];
                    return (
                      <Tooltip key={t.id} content={t.stage} side="top">
                        <button type="button" aria-pressed={view.settings.theme === t.id} disabled={busy} onClick={() => look(t.id)}>
                          {usual && <LayoutThumb view={view} layout={usual.layout} />}
                          {LOOKS[t.id] ?? t.name}
                        </button>
                      </Tooltip>
                    );
                  })}
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
            <dd title={view.options.narrator.ready ? undefined : "Narration needs ELEVENLABS_API_KEY"}>
              <SegmentedControl
                size="sm"
                value={view.settings.voice}
                disabled={busy}
                onChange={(voice) => voice !== view.settings.voice && void set({ voice })}
                options={[
                  { value: "live", label: presenterOff ? "Recorded" : "Your voice" },
                  { value: "narrator", label: "Narrator", disabled: !view.options.narrator.ready },
                ]}
              />
              {view.settings.voice === "narrator" && view.options.narrator.ready && <NarratorVoice view={view} run={run} busy={busy} />}
            </dd>
          </div>
          <div>
            <dt>Pictures</dt>
            <dd>
              <SegmentedControl
                size="sm"
                value={view.settings.level}
                disabled={busy}
                onChange={(level) => level !== view.settings.level && void set({ level })}
                options={[
                  { value: "simple", label: "Simple" },
                  { value: "rich", label: "Rich" },
                ]}
              />
              <small>{view.settings.level === "rich" ? "Posed as stills for your go before they count" : "Made at once from the plan"}</small>
            </dd>
          </div>
        </dl>
      </section>
    </main>
  );
}

// One chapter: the script, the frame for the picked line, that line's choices.
function Chapter({
  view,
  chapter,
  run,
  busy,
  record,
  onAt,
  waiting,
  marks,
}: {
  view: EpisodeView;
  chapter: EpisodeChapter;
  run: Run;
  busy: boolean;
  record: boolean;
  onAt: (at: string, record?: boolean) => void;
  waiting: Waiting;
  marks: Marks;
}) {
  const plan = view.plan!;
  const lines = useMemo(() => linesOf(chapter), [chapter]);
  const number = plan.chapters.indexOf(chapter) + 1;
  const [picked, setPicked] = useState(lines[0].id);
  const [editing, setEditing] = useState<string | null>(null);
  const [playing, setPlaying] = useState<Playing>(null);
  // One line recorded again on its own, over the chapter's take.
  const [solo, setSolo] = useState<string | null>(null);
  const arming = useRef(false);
  const upload = useRef<HTMLInputElement>(null);
  const ask = useRef<AskHandle>(null);
  const take = takeOf(view, chapter.id);
  const presenterOff = view.settings.presenter === "off";
  const working = turning(view);

  const save = useCallback(
    async (recording: Recording) => {
      await run(() => api.addTake(view.id, { chapter: chapter.id, frame: solo ?? undefined, marks: recording.marks, file: recording.blob, name: recording.name }));
      setSolo(null);
    },
    [run, view.id, chapter.id, solo],
  );
  const frames = useMemo(() => (solo ? [solo] : lines.map((l) => l.id)), [solo, lines]);
  const recorder = useRecorder({ frames, camera: !presenterOff, onDone: save });
  const recording = recorder.state !== "off";
  const said = solo ? lines.find((l) => l.id === solo) : lines[recorder.index];
  const line = (recording && recorder.state !== "saving" ? said : undefined) ?? lines.find((l) => l.id === picked) ?? lines[0];
  const unit = unitOf(view, line.id);
  const at = lines.indexOf(line);
  const state = chapterState(view, chapter);
  const following = plan.chapters[number];
  // How long the take was planned to run: the chapter, or the one line said again.
  const planned = solo ? (lines.find((l) => l.id === solo)?.seconds ?? 0) : (view.clock?.chapters.find((c) => c.id === chapter.id)?.seconds ?? chapter.seconds);
  const [sayStep, setSayStep] = useSayStep();
  const changed = useMemo(() => new Set([...(view.last_change?.lines ?? []), ...(view.last_change?.added ?? [])]), [view.last_change]);
  // What the last change did, laid into the script: what each changed line said before, and
  // the lines it cut, each after the line it followed.
  const marked = marks.on && !recording;
  const was = view.last_change?.was ?? {};
  const cuts = useMemo(() => {
    const by = new Map<string, string[]>();
    for (const c of view.last_change?.cut ?? []) {
      if (c.chapter !== chapter.id) continue;
      const after = lines.some((l) => l.id === c.after) ? c.after : "";
      by.set(after, [...(by.get(after) ?? []), c.says]);
    }
    return by;
  }, [view.last_change, chapter.id, lines]);
  const cutRows = (after: string) =>
    marked &&
    cuts.get(after)?.map((says, n) => (
      <li key={`cut-${after}-${n}`} className="ep-line-cut">
        <del>{says}</del>
        <small>Cut</small>
      </li>
    ));

  // A line picked to be said again: the recorder is armed once it knows it has one line.
  const arm = recorder.arm;
  // Opened to be recorded (the chapter before was just recorded): the camera comes up at once.
  const opened = useRef(false);
  useEffect(() => {
    if (!record || opened.current) return;
    opened.current = true;
    void arm();
  }, [record, arm]);
  useEffect(() => {
    if (!solo || !arming.current) return;
    arming.current = false;
    void arm();
  }, [solo, arm]);
  useEffect(() => {
    if (recorder.state === "off" && !arming.current) setSolo(null);
  }, [recorder.state]);
  const recordLine = (frame: string) => {
    arming.current = true;
    setPlaying(null);
    setPicked(frame);
    setSolo(frame);
  };

  // Space starts the take once the camera is ready, then starts each next line (so does the
  // right arrow).
  useEffect(() => {
    if (recorder.state !== "recording" && recorder.state !== "ready") return;
    const onKey = (e: KeyboardEvent) => {
      if (recorder.state === "ready") {
        if (e.key !== " ") return;
        e.preventDefault();
        recorder.start();
      } else if (e.key === " " || e.key === "ArrowRight" || e.key === "Enter") {
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
    setEditing(null);
    setPicked(frame);
  };
  const reword = (frame: string, text: string) => {
    setEditing(null);
    void run(() => api.editLine(view.id, frame, text));
  };
  const canEdit = !recording && !working && !busy;

  // Up and down move through the lines, Enter changes the words, a slash asks for a change.
  useEffect(() => {
    if (recording || editing) return;
    const onKey = (e: KeyboardEvent) => {
      const on = e.target as HTMLElement;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (on.closest("textarea, input, select, [contenteditable], [role=menu], [role=alertdialog], [role=radiogroup], details")) return;
      if (e.key === "ArrowDown" && at < lines.length - 1) {
        e.preventDefault();
        pick(lines[at + 1].id);
      } else if (e.key === "ArrowUp" && at > 0) {
        e.preventDefault();
        pick(lines[at - 1].id);
      } else if (e.key === "Enter" && canEdit && (on === document.body || on.classList.contains("ep-line"))) {
        e.preventDefault();
        setEditing(line.id);
      } else if (e.key === "/") {
        e.preventDefault();
        ask.current?.open();
      } else if ((e.key === "r" || e.key === "R") && !busy) {
        e.preventDefault();
        void recorder.arm();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // What a change can be about, nearest first: this line, its picture, the chapter, the film.
  const targets: AskTarget[] = [
    { scope: "line", target: line.id, label: "This line", name: `Ch ${number} · line ${at + 1}`, hint: "Ask for a change to this line", presets: ["Shorter", "Plainer words", "Cut this line"] },
    ...(unit?.kind === "picture"
      ? [{ scope: "picture" as const, target: line.id, label: "Its picture", name: `Ch ${number} · picture of line ${at + 1}`, hint: "Ask for a change to this picture", presets: ["Simpler", "Larger text", "Show it another way"] }]
      : []),
    { scope: "chapter", target: chapter.id, label: "This chapter", name: `Chapter ${number}`, hint: "Ask for a change to this chapter", presets: ["Shorter", "Add an example", "Open with a question"] },
    { scope: "film", label: "The whole film", name: "The film", hint: "Ask for a change to the film", presets: ["Make it shorter", "A stronger opening", "Plainer words"] },
  ];

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
          {cutRows("")}
          {lines.flatMap((l, i) => {
            const mine = unitOf(view, l.id);
            const leads = mine && mine.frames[0] === l.id;
            const current = l.id === line.id;
            const again = view.rerecord.includes(l.id);
            const before = marked ? was[l.id] : undefined;
            return [
              <li key={l.id}>
                {leads && (
                  <p className="ep-unit" data-status={!view.approved ? "planned" : mine.kind === "undesigned" ? "making" : mine.picture.status}>
                    {PICTURES[mine.kind_of_picture] ?? "Picture"} · {mine.level === "rich" ? "Rich" : "Simple"} · {pictureWords(mine, view.approved)}
                  </p>
                )}
                {editing === l.id ? (
                  <LineEditor line={l} onSave={(text) => reword(l.id, text)} onCancel={() => setEditing(null)} />
                ) : (
                  <div className="ep-line-card" data-current={current || undefined}>
                    <button
                      type="button"
                      className="ep-line"
                      aria-current={current || undefined}
                      disabled={recording}
                      onClick={() => pick(l.id)}
                      onDoubleClick={() => canEdit && setEditing(l.id)}
                    >
                      <i className="ep-who" data-presence={l.presence} aria-label={PRESENCE[l.presence]} />
                      {before ? <Changed was={before} now={l.vo} /> : <span>{l.vo}</span>}
                      {/* the picked line says where it stands under its words, beside its tools */}
                      {recording ? i < recorder.index && !solo && <small>✓</small> : current ? null : again ? <small data-tone="amber">Say again</small> : take && <small aria-label="Recorded">✓</small>}
                      {!recording && !current && !before && changed.has(l.id) && <em aria-label="Changed" />}
                    </button>
                    {current && !recording && (
                      <div className="ep-line-foot">
                        <small data-tone={again ? "amber" : undefined}>{again ? "Say again" : take ? "Recorded" : changed.has(l.id) && !before ? "Changed" : ""}</small>
                        {before && (
                          <Tooltip content="Put the old words back" side="bottom">
                            <button type="button" className="icon-btn" aria-label="Put the old words back" disabled={!canEdit} onClick={() => reword(l.id, before)}>
                              <Undo2 />
                            </button>
                          </Tooltip>
                        )}
                        <Tooltip content="Change the words" shortcut="↵" side="bottom">
                          <button type="button" className="icon-btn" aria-label="Change the words" disabled={!canEdit} onClick={() => setEditing(l.id)}>
                            <Pencil />
                          </button>
                        </Tooltip>
                        {take && (
                          <Tooltip content="Record this line again" side="bottom">
                            <button type="button" className="icon-btn" aria-label="Record this line again" disabled={busy} onClick={() => recordLine(l.id)}>
                              <Mic />
                            </button>
                          </Tooltip>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </li>,
              cutRows(l.id),
            ];
          })}
        </ol>
        {!recording && <Ask ref={ask} view={view} targets={targets} run={run} busy={busy} slash waiting={waiting} marks={marks} />}
      </section>

      <section className="ep-middle">
        <FileDrop
          className="ep-stage-wrap"
          label={`Drop a recording of chapter ${number}`}
          refusal="A recording is a video or an audio file."
          one
          disabled={recording || busy}
          accepts={(file) => /^(video|audio)\//.test(file.type) || /\.(mp4|mov|m4v|webm|mkv|m4a|mp3|wav|aac|ogg)$/i.test(file.name)}
          onFiles={([file]) => void run(() => api.addTake(view.id, { chapter: chapter.id, marks: [], file, name: file.name }))}
        >
          <Stage view={view} frame={line} unit={unit} take={recording ? undefined : take} stream={recorder.stream} playing={playing} onEnded={() => setPlaying(null)} />
          {recorder.state === "count" && <span className="ep-count">{recorder.count}</span>}
        </FileDrop>
        {recording ? (
          <div className="ep-recbar" data-recording>
            {recorder.state === "asking" && (
              <span className="ep-said">
                <span className="spin" />
                Waiting for the camera and microphone
              </span>
            )}
            {recorder.state === "ready" && (
              <>
                <button type="button" className="btn primary" onClick={recorder.start}>
                  <Circle />
                  Start recording
                  <Kbd keys="space" size="sm" />
                </button>
                <Devices stream={recorder.stream} devices={recorder.devices} using={recorder.using} camera={!presenterOff} onChoose={recorder.choose} />
                <span className="faint">{solo ? "Press Space when you have said it." : "Press Space at the end of each line."}</span>
              </>
            )}
            {recorder.state === "count" && <span className="ep-said">Get ready</span>}
            {recorder.state === "recording" && (
              <>
                <span className="ep-live-dot" />
                <b className="ep-timer">{mmss(recorder.elapsed)}</b>
                {planned > 0 && (
                  <span className="ep-planned" data-over={recorder.elapsed > planned * 1.25 || undefined}>
                    of {mmss(planned)}
                  </span>
                )}
                <Level stream={recorder.stream} />
                <button type="button" className="btn primary" onClick={recorder.next}>
                  {solo || recorder.index + 1 >= lines.length ? "Finish" : "Next line"}
                  <Kbd keys="space" size="sm" />
                </button>
              </>
            )}
            {recorder.state === "saving" && (
              <span className="ep-said">
                <span className="spin" />
                Saving the take
              </span>
            )}
            {recorder.state !== "saving" && (
              <button type="button" className="btn" onClick={() => recorder.stop(false)}>
                Cancel
              </button>
            )}
          </div>
        ) : (
          <div className="ep-controls">
            <Tooltip content="The line before" shortcut="↑" side="bottom">
              <button type="button" className="icon-btn" aria-label="Previous line" disabled={at === 0} onClick={() => pick(lines[at - 1].id)}>
                <ChevronLeft />
              </button>
            </Tooltip>
            <span className="ep-pos">
              Line {at + 1} of {lines.length}
            </span>
            <Tooltip content="The line after" shortcut="↓" side="bottom">
              <button type="button" className="icon-btn" aria-label="Next line" disabled={at === lines.length - 1} onClick={() => pick(lines[at + 1].id)}>
                <ChevronRight />
              </button>
            </Tooltip>
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
            <Tooltip content="Bring a recording of this chapter: pick a video or audio file, or drop one on the frame" side="bottom">
              <button type="button" className="icon-btn" aria-label="Bring a recording of this chapter" disabled={busy} onClick={() => upload.current?.click()}>
                <Upload />
              </button>
            </Tooltip>
            <Tooltip content="Opens the camera and microphone" shortcut="R" side="top">
              <button type="button" className={`btn ${take ? "" : "primary"}`} disabled={busy} onClick={() => void recorder.arm()}>
                <Circle />
                {take ? "Retake" : `Record chapter ${number}`}
              </button>
            </Tooltip>
            {take &&
              (following ? (
                takeOf(view, following.id) ? (
                  <button type="button" className="btn primary" onClick={() => onAt(following.id)}>
                    Chapter {number + 1}
                    <ArrowRight />
                  </button>
                ) : (
                  <Tooltip content="Opens it with the camera on, ready for Space" side="top" align="end">
                    <button type="button" className="btn primary" onClick={() => onAt(following.id, true)}>
                      <Circle />
                      Record chapter {number + 1}
                    </button>
                  </Tooltip>
                )
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
        {!recording && !take && view.approved && state === "making" && <p className="ep-notice">You can record now. The pictures are finished meanwhile and timed to your take.</p>}
      </section>

      {recording ? (
        <section className="ep-say" aria-label="Say it" aria-live="polite" style={{ "--say": `${SAY_SIZES[sayStep]}px` } as React.CSSProperties}>
          <header>
            <p className="ep-kicker">{solo ? `Say it again · line ${at + 1}` : `Say it · line ${Math.min(recorder.index + 1, lines.length)} of ${lines.length}`}</p>
            <span className="ep-say-size" role="group" aria-label="The size of the words">
              <button type="button" aria-label="Smaller words" disabled={sayStep === 0} onClick={() => setSayStep(sayStep - 1)}>
                A
              </button>
              <button type="button" aria-label="Larger words" disabled={sayStep === SAY_SIZES.length - 1} onClick={() => setSayStep(sayStep + 1)}>
                A
              </button>
            </span>
          </header>
          <p className="ep-say-now">{line.vo}</p>
          {!solo && lines[recorder.index + 1] && <p className="ep-say-next">{lines[recorder.index + 1].vo}</p>}
        </section>
      ) : (
        <Choices view={view} chapter={chapter} line={line} unit={unit} run={run} busy={busy || working} onFilm={() => onAt(FILM)} onAskPicture={() => ask.current?.open("picture")} />
      )}
    </main>
  );
}

// How large the words to say are drawn, in steps: a person reads them from where they stand to
// be filmed, which is rarely where they sit to type. Kept on this computer.
const SAY_SIZES = [18, 22, 28, 36];
function useSayStep(): [number, (step: number) => void] {
  const [step, setStep] = useState(() => {
    try {
      const kept = Number(localStorage.getItem("episode-say-size") ?? 1);
      return Number.isInteger(kept) && kept >= 0 && kept < SAY_SIZES.length ? kept : 1;
    } catch {
      return 1;
    }
  });
  const set = (to: number) => {
    setStep(to);
    try {
      localStorage.setItem("episode-say-size", String(to));
    } catch {
      // kept for this visit only
    }
  };
  return [step, set];
}

// A line's words, changed where they are read. Enter keeps them, Escape leaves them as they
// were, and clicking away keeps them too.
function LineEditor({ line, onSave, onCancel }: { line: EpisodeFrame; onSave: (text: string) => void; onCancel: () => void }) {
  const [text, setText] = useState(line.vo);
  const field = useRef<HTMLTextAreaElement>(null);
  const done = useRef(false);
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  // the plan's own pace for this line, so the seconds read as the rest of the script's do
  const pace = line.words && line.seconds ? line.words / line.seconds : 2.6;

  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);
  useEffect(() => {
    const el = field.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);

  const finish = (keep: boolean) => {
    if (done.current) return;
    done.current = true;
    const said = text.trim().replace(/\s+/g, " ");
    if (keep && said && said !== line.vo) onSave(said);
    else onCancel();
  };
  return (
    <div className="ep-line-edit">
      <textarea
        ref={field}
        rows={1}
        value={text}
        aria-label="The words of this line"
        onChange={(e) => setText(e.target.value)}
        onBlur={() => finish(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            finish(true);
          } else if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            finish(false);
          }
        }}
      />
      <p>
        <span>
          {words} {words === 1 ? "word" : "words"} · about {Math.max(1, Math.round(words / pace))} s
        </span>
        <span>
          <Kbd keys="enter" size="sm" /> keeps it · <Kbd keys="esc" size="sm" /> leaves it
        </span>
      </p>
    </div>
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
