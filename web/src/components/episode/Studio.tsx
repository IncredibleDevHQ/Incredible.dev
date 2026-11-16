// An episode's studio, over the channel: the plan and the studio in one place. The bar holds the
// film's title, its own choices (look, voice, pictures), where its pictures stand and, once it is
// rendered, its file. Every page is the same three columns: the film and its chapters as slides,
// a document in the middle (the whole script on the film's page, one chapter's on a chapter's),
// and the frame on the right. Words are changed where they are read; anything else is asked for
// at the caret, about the line, its picture, the chapter or the film (the film's page keeps a
// change bar of its own). Recording happens in the same screen.
import {
  ArrowLeft,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Circle,
  Maximize2,
  Minimize2,
  Monitor,
  Moon,
  RotateCcw,
  Sparkles,
  Square,
  Sun,
  Upload,
} from "lucide-react";
import { flushSync } from "react-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type EpisodeAsk, type EpisodeChapter, type EpisodeView, type WriterId } from "../../api";
import { chapterName, clockLine, resizePresenter, LAYOUTS, linesOf, mmss, pictureCount, takeOf, unitOf } from "../../episode";
import { useHouse } from "../../store";
import { useTheme } from "../../theme";
import { AgentMark } from "../../ui";
import { FileDrop } from "../FileDrop";
import { Kbd } from "../Kbd";
import { Select } from "../Select";
import { Tooltip } from "../Tooltip";
import { Ask, turning, useWaiting, type Marks, type Run, type Waiting } from "./Ask";
import { ChoicePanel, PANELS, type Panel } from "./Choices";
import { Devices, Level } from "./Devices";
import { useRecorder, type Recording } from "./recorder";
import { FilmPage, RenderStatus, WRITERS, type Open } from "./Film";
import { Script, type ScriptHandle } from "./Script";
import { agentOptions, Stills } from "./Picture";
import { FILM, Slides } from "./Slides";
import { LinePlayer } from "./LinePlayer";
import { FrameCanvas } from "./FrameCanvas";
import { spansOf, Timeline } from "./Timeline";
import { Stage } from "./Stage";
import { ApplyChanges, FilmDownload, FilmTools } from "./Tools";
import { WorkPill, WorkTrail } from "./Work";

export function EpisodeStudio() {
  const view = useHouse((s) => s.episode);
  const openEpisode = useHouse((s) => s.openEpisode);
  const [at, setAt] = useState<string>(FILM);
  // The chapter that opens next is to be recorded at once: the run-through, once the choices are
  // made. It opens at a line when one was picked on the film's page.
  const [recordNext, setRecordNext] = useState(false);
  const [lineNext, setLineNext] = useState<string | null>(null);
  // the frame's pop-up stays open when the carousel moves it to another chapter
  const [popNext, setPopNext] = useState(false);
  const [busy, setBusy] = useState(false);
  const go = useCallback<Open>((to, record = false, line, pop = false) => {
    setRecordNext(record);
    setLineNext(line ?? null);
    setPopNext(pop);
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
      // the frame open full screen closes first; a menu or a question in it closes before that
      if (e.key !== "Escape" || e.defaultPrevented || document.querySelector(".ep-full")) return;
      if (!(e.target as HTMLElement).closest("textarea, input, [data-recording]")) void openEpisode(null);
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
      <Bar view={view} ready={ready} onAt={go} onClose={() => void openEpisode(null)} run={run} busy={busy} />
      {!ready || !plan ? (
        <Planning view={view} run={run} busy={busy} />
      ) : chapter ? (
        <Chapter key={chapter.id} view={view} chapter={chapter} run={run} busy={busy} record={recordNext} line={lineNext} pop={popNext} onAt={go} waiting={waiting} marks={marks} />
      ) : (
        <FilmPage view={view} run={run} busy={busy} onAt={go} waiting={waiting} />
      )}
    </div>
  );
}

// The film's title, its own choices, where its pictures stand, its file once rendered, and light
// or dark. The slides under it are the way between the film and its chapters.
function Bar({ view, ready, onAt, onClose, run, busy }: { view: EpisodeView; ready: boolean; onAt: (at: string) => void; onClose: () => void; run: Run; busy: boolean }) {
  return (
    <header className="ep-bar">
      <Tooltip content="Back to the canvas" shortcut="Esc" side="bottom" align="start">
        <button type="button" className="icon-btn" aria-label="Back to the canvas" onClick={onClose}>
          <ArrowLeft />
        </button>
      </Tooltip>
      <h2>{view.title}</h2>
      {ready && <FilmTools view={view} run={run} busy={busy} />}
      <span className="ep-gap" />
      {ready && <Now view={view} run={run} busy={busy} onAt={onAt} />}
      {ready && <FilmDownload view={view} />}
      <Appearance />
    </header>
  );
}

// Light or dark, as the sidebar sets it, at hand while the studio covers the sidebar: two icons,
// the one in use pressed.
function Appearance() {
  const [, setTheme, chosen] = useTheme();
  const looks = [
    { pick: "light", label: "Light", Icon: Sun },
    { pick: "dark", label: "Dark", Icon: Moon },
    { pick: "system", label: "As the system is", Icon: Monitor },
  ] as const;
  return (
    <div className="ep-appearance" role="group" aria-label="Appearance">
      {looks.map(({ pick, label, Icon }) => (
        <Tooltip key={pick} content={label} side="bottom" align="end">
          <button type="button" aria-label={label} aria-pressed={chosen === pick} onClick={() => setTheme(pick)}>
            <Icon />
          </button>
        </Tooltip>
      ))}
    </div>
  );
}

// Where the pictures stand, the changes that wait to be applied, and the way to make the pictures
// nobody asked for yet: all of them at once, or the rest once some were made a chapter or a
// picture at a time. Once the plan is approved, applying the changes makes the new ones too.
function Now({ view, run, busy, onAt }: { view: EpisodeView; run: Run; busy: boolean; onAt: (at: string) => void }) {
  const pictures = pictureCount(view);
  const asked = pictures.all - pictures.planned;
  const first = asked === 0 && view.waiting.length === 0;
  return (
    <div className="ep-now">
      {asked > 0 && <WorkPill view={view} run={run} busy={busy} onAt={onAt} />}
      <ApplyChanges view={view} run={run} busy={busy} />
      {pictures.planned > 0 && !view.approved && (
        <Tooltip content={`Draws the ${pictures.planned} ${pictures.planned === 1 ? "picture" : "pictures"} not made yet. Everything can still change after.`} side="bottom" align="end">
          <button type="button" className={`btn ${first ? "primary" : ""}`} disabled={busy || turning(view)} onClick={() => void run(() => api.approveEpisode(view.id))}>
            {asked ? `Make the other ${pictures.planned}` : "Make the pictures"}
          </button>
        </Tooltip>
      )}
    </div>
  );
}

// While the plan is being written: where the writer is, and what it has put down so far.
function Planning({ view, run, busy }: { view: EpisodeView; run: Run; busy: boolean }) {
  const stage = view.stage;
  const failed = view.status === "failed";
  const writers = view.options.writers.filter((w) => w.ready);
  const [writer, setWriter] = useState<WriterId>(view.writer);
  return (
    <main className="ep-plan">
      <section className="ep-plan-main">
        <p className="ep-kicker">{failed ? "The plan stopped" : `Planning with ${WRITERS[view.writer] ?? "an agent"}`}</p>
        <h1>{view.written.idea || view.title}</h1>
        <WorkTrail view={view} />
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

// The key that opens the prompt at the caret, as this computer writes it.
const ASK_KEYS = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘J" : "Ctrl+J";

// One chapter: the script, the frame for the picked line, that line's choices.
function Chapter({
  view,
  chapter,
  run,
  busy,
  record,
  line: opening,
  pop,
  onAt,
  waiting,
  marks,
}: {
  view: EpisodeView;
  chapter: EpisodeChapter;
  run: Run;
  busy: boolean;
  record: boolean;
  line: string | null;
  pop: boolean;
  onAt: Open;
  waiting: Waiting;
  marks: Marks;
}) {
  const plan = view.plan!;
  const lines = useMemo(() => linesOf(chapter), [chapter]);
  const number = plan.chapters.indexOf(chapter) + 1;
  const [picked, setPicked] = useState(() => (opening && lines.some((l) => l.id === opening) ? opening : lines[0].id));
  const [progress, setProgress] = useState<number | null>(null);
  const [captions, setCaptions] = useCaptions();
  // The editor expands above the script. Recording brings the same frame into a dialog.
  const [full, setFull] = useState(pop);
  const [selected, setSelected] = useState(Boolean(opening || pop));
  const [speed, setSpeed] = useState(1);
  const scriptBody = useRef<HTMLDivElement>(null);
  // the rail's panel, kept as the pop-up moves between chapters
  const [panel, setPanelNow] = useState<Panel>(lastPanel);
  const setPanel = (to: Panel) => {
    lastPanel = to;
    setPanelNow(to);
  };
  // One line recorded again on its own, over the chapter's take.
  const [solo, setSolo] = useState<string | null>(null);
  const arming = useRef(false);
  const upload = useRef<HTMLInputElement>(null);
  const script = useRef<ScriptHandle>(null);
  const take = takeOf(view, chapter.id);
  const sayAgain = lines.filter((l) => view.rerecord.includes(l.id)).length;
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
  const scheduled = clockLine(view, line.id);
  const [resizing, setResizing] = useState<{line: string; size: number} | null>(null);
  const draftSize = resizing?.line === line.id ? resizing.size : null;
  const previewLine = draftSize === null ? line : resizePresenter(view, line, draftSize);
  const playerKey = [line.id, view.film_state.stale, view.film_state.file?.id, view.settings.voice, unit?.picture.clip?.id, scheduled?.audio_url, scheduled?.source.take].join("/");
  const following = plan.chapters[number];
  const previous = number > 1 ? plan.chapters[number - 2] : undefined;
  // How long the take was planned to run: the chapter, or the one line said again.
  const planned = solo ? (lines.find((l) => l.id === solo)?.seconds ?? 0) : (view.clock?.chapters.find((c) => c.id === chapter.id)?.seconds ?? chapter.seconds);
  const [sayStep, setSayStep] = useSayStep();
  // What the last change did is marked in the script, except while a take is recorded.
  const marked = marks.on && !recording;
  // A line picked to be said again: the recorder is armed once it knows it has one line.
  const arm = recorder.arm;
  // A chapter is said over its pictures, so they are made before it is recorded. Asking to
  // record a chapter whose pictures nobody asked for yet makes them; the camera opens once
  // none is still on its way.
  const pics = pictureCount(view, chapter.id);
  const waits = pics.planned + pics.making;
  const agents = agentOptions(view);
  const episode = view.id;
  const begin = useCallback(() => {
    if (pics.planned > 0) return void run(() => api.makePictures(episode, { chapter: chapter.id }));
    if (pics.making > 0) return;
    setFull(true);
    void arm();
  }, [pics.planned, pics.making, run, episode, chapter.id, arm]);
  // Opened to be recorded (the chapter before was just recorded): the camera comes up at once.
  const opened = useRef(false);
  useEffect(() => {
    if (!record || opened.current) return;
    opened.current = true;
    begin();
  }, [record, begin]);
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
    setProgress(null);
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

  const span = spansOf(view, chapter, lines).spans.find((x) => x.line.id === line.id);
  const playhead = span && progress !== null ? span.start + progress * span.seconds : null;
  const pick = (frame: string) => {
    setSelected(true);
    if (frame === picked) return;
    const select = () => {
      setProgress(null);
      setPicked(frame);
    };
    const person = () => fullRef.current?.querySelector<HTMLElement>(".ep-stage-person");
    const before = full && !recording ? person() : null;
    if (!before || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return select();
    const geometry = (element: HTMLElement): Keyframe => {
      const { left, top, width, height, borderRadius } = getComputedStyle(element);
      return { left, top, width, height, borderRadius };
    };
    const start = geometry(before);
    flushSync(select);
    const after = person();
    if (after) after.animate([start, geometry(after)], { duration: 450, easing: "ease-in-out" });
  };
  const reword = (frame: string, text: string) => void run(() => api.editLine(view.id, frame, text));

  const fullRef = useRef<HTMLDivElement>(null);
  const peekRef = useRef<HTMLButtonElement>(null);
  const scriptScroll = useRef(0);
  const transition = useRef<ViewTransition | null>(null);
  const toggleEditor = useCallback((open: boolean) => {
    const scroller = scriptBody.current;
    if (open) scriptScroll.current = scroller?.scrollTop ?? 0;
    const source = open ? peekRef.current : fullRef.current?.querySelector<HTMLElement>(".ep-pop-stage");
    const from = source?.getBoundingClientRect();
    const update = () => {
      flushSync(() => { setFull(open); setSelected(open); });
      if (scroller) scroller.scrollTop = open ? 0 : scriptScroll.current;
    };
    transition.current?.skipTransition();
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { update(); return; }
    if (document.startViewTransition) {
      transition.current = document.startViewTransition(update);
    } else {
      update();
      const target = open ? fullRef.current?.querySelector<HTMLElement>(".ep-pop-stage") : peekRef.current;
      if (from && target) {
        const to = target.getBoundingClientRect();
        if (to.width && to.height) target.animate([
          {transformOrigin:"top left", transform:`translate(${from.left-to.left}px,${from.top-to.top}px) scale(${from.width/to.width},${from.height/to.height})`},
          {transformOrigin:"top left", transform:"none"}
        ], {duration:620, easing:"cubic-bezier(.45,0,.2,1)"});
      }
    }
  }, []);
  const wasFull = useRef(false);
  const askAfter = useRef(false);
  useEffect(() => {
    if (recording) setFull(true);
  }, [recording]);
  useEffect(() => {
    if (full) { fullRef.current?.focus({ preventScroll: true }); }
    else if (askAfter.current) script.current?.askAt(line.id, "picture");
    else if (wasFull.current) peekRef.current?.focus({ preventScroll: true });
    askAfter.current = false;
    wasFull.current = full;
  }, [full]);
  useEffect(() => {
    if (!full || recording) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || (e.target as HTMLElement).closest("textarea, input")) return;
      e.preventDefault();
      toggleEditor(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full, recording]);

  // Outside the script, up and down move through the lines, Enter puts the caret at the end of
  // the picked one, and a slash opens the blocks there.
  useEffect(() => {
    if (recording) return;
    const onKey = (e: KeyboardEvent) => {
      const on = e.target as HTMLElement;
      // the prompt at the caret, from anywhere outside a field (in the script, the editor has it)
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "j" && !e.defaultPrevented && !full && !on.closest('textarea, input, select, [contenteditable="true"]')) {
        e.preventDefault();
        script.current?.askAt(line.id, "line");
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (on.closest("textarea, input, select, [contenteditable], [role=menu], [role=alertdialog], [role=radiogroup], details")) return;
      if (e.key === "ArrowDown" && at < lines.length - 1) {
        e.preventDefault();
        pick(lines[at + 1].id);
      } else if (e.key === "ArrowUp" && at > 0) {
        e.preventDefault();
        pick(lines[at - 1].id);
      } else if (e.key === "Enter" && !working && !full && on === document.body) {
        e.preventDefault();
        script.current?.focusLine(line.id);
      } else if (e.key === "/" && !working && !full) {
        e.preventDefault();
        script.current?.focusLine(line.id, true);
      } else if ((e.key === "c" || e.key === "C") && full) {
        e.preventDefault();
        setCaptions(!captions);
      } else if ((e.key === "r" || e.key === "R") && !busy) {
        e.preventDefault();
        begin();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // A take of the chapter from a file: picked, or dropped on the frame.
  const takesFile = (file: File) => /^(video|audio)\//.test(file.type) || /\.(mp4|mov|m4v|webm|mkv|m4a|mp3|wav|aac|ogg)$/i.test(file.name);
  const bring = (file: File) => void run(() => api.addTake(view.id, { chapter: chapter.id, marks: [], file, name: file.name }));
  // After a take, the way on: the next chapter (opened with the camera on when it has no take
  // yet), or the film.
  const onward =
    take &&
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
    ));

  const previewTake = scheduled?.source.kind === "take" ? view.takes.find(t => t.id === scheduled.source.take) : undefined;
  const artwork = line.presence === "person" && !previewTake?.video
    ? view.units.filter(u => u.chapter === chapter.id).flatMap(u => Object.values(u.picture.stills))[0]
    : undefined;
  const chapterActions = (
    <div className="ep-doc-top">
      <p className="ep-kicker">
        Chapter {number} · {chapterName(chapter)} · {mmss(view.clock?.chapters.find((c) => c.id === chapter.id)?.seconds ?? chapter.seconds)}
      </p>
      <div className="ep-doc-actions">
        {/* where more than one agent is ready, a chapter's pictures can be another's to draw */}
        {pics.all > 0 && agents.length > 1 && (
          <label className="ep-figure-by">
            Pictures by
            <Select
              size="sm"
              aria-label={`The agent that draws chapter ${number}'s pictures`}
              value={view.builders[chapter.id]}
              options={agents}
              disabled={busy || recording}
              onChange={(id) =>
                id !== view.builders[chapter.id] && void run(() => api.chooseEpisode(view.id, { builders: { [chapter.id]: id === view.settings.writer ? null : (id as WriterId) } }))
              }
            />
          </label>
        )}
        {take && (
          <small className="ep-peek-take">
            Take {take.n} · {mmss(take.seconds)}
          </small>
        )}
        <Tooltip content="Asks the writer for a change, at the caret" shortcut={ASK_KEYS} side="bottom" align="end">
          <button type="button" className="btn" disabled={recording} onClick={() => script.current?.askAt(line.id, "chapter")}>
            <Sparkles />
            Ask AI
          </button>
        </Tooltip>
        <Tooltip content={pics.planned ? "Makes this chapter's pictures first" : "Opens the camera and microphone"} shortcut="R" side="bottom" align="end">
          <button type="button" className={`btn ${take ? "" : "primary"}`} disabled={busy || (waits > 0 && pics.planned === 0)} onClick={begin}>
            <Circle />
            {take ? "Retake" : `Record chapter ${number}`}
          </button>
        </Tooltip>
        {onward}
      </div>
    </div>
  );
  const choiceRail = (
    <nav className="ep-pop-rail" aria-label="Choices for this line">
      {!recording && (
          <Tooltip content="Back to the script" shortcut="Esc" side="bottom" align="start">
            <button type="button" className="icon-btn ep-collapse" aria-label="Back to the script" onClick={() => toggleEditor(false)}>
              <Minimize2 />
            </button>
          </Tooltip>
        )}
      {PANELS.map(({ id, label, icon: Icon }) => (
        <button key={id} type="button" aria-pressed={!recording && panel === id} disabled={recording} onClick={() => setPanel(id)}>
          <Icon aria-hidden="true" />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
  return (
    <main className="ep-chapter" data-recording={recording || undefined}>
      <Slides view={view} at={chapter.id} onAt={(id) => onAt(id)} />

      <section className="ep-doc ep-chapter-sheet" aria-label="Script">
        <div className="ep-doc-body" ref={scriptBody}>
      {full && (
        <div className={recording ? "ep-pop-scrim" : undefined}>
          <div
            ref={fullRef}
            className={recording ? "ep-full ep-pop" : "ep-full ep-pop ep-inline-player"}
            role={recording ? "dialog" : "region"}
            aria-modal={recording || undefined}
            aria-label={`Chapter ${number}: the frame, its choices and the recorder`}
            tabIndex={-1}
            data-recording={recording || undefined}
          >
            <section className="ep-pop-main">
              <header className="ep-pop-head">
                <b>Chapter {number}</b>
                <span>
                  {chapterName(chapter)}
                </span>
                <span className="ep-gap" />
                {!recording && <div className="ep-preview-actions"><FilmDownload view={view} />
                  <Tooltip content="Bring a recording of this chapter: pick a video or audio file, or drop one on the frame" side="bottom">
                    <button type="button" className="icon-btn" aria-label="Bring a recording of this chapter" disabled={busy} onClick={() => upload.current?.click()}>
                      <Upload />
                    </button>
                  </Tooltip>
                  <input
                    ref={upload}
                    type="file"
                    accept="video/*,audio/*"
                    hidden
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      e.target.value = "";
                      if (file) bring(file);
                    }}
                  />
                </div>}
                {!recording && (
                  <span className="ep-pop-chapters" role="group" aria-label="Chapters">
                    <Tooltip content={previous ? `Chapter ${number - 1}` : "The first chapter"} side="bottom">
                      <button type="button" className="icon-btn" aria-label="The chapter before" disabled={!previous} onClick={() => previous && onAt(previous.id, false, undefined, true)}>
                        <ChevronLeft />
                      </button>
                    </Tooltip>

                    <Tooltip content={following ? `Chapter ${number + 1}` : "The last chapter"} side="bottom" align="end">
                      <button type="button" className="icon-btn" aria-label="The chapter after" disabled={!following} onClick={() => following && onAt(following.id, false, undefined, true)}>
                        <ChevronRight />
                      </button>
                    </Tooltip>
                  </span>
                )}
              </header>
              <div className="ep-pop-frame">
                <FileDrop
                  className="ep-pop-stage"
                  label={`Drop a recording of chapter ${number}`}
                  refusal="A recording is a video or an audio file."
                  one
                  disabled={recording || busy}
                  accepts={takesFile}
                  onFiles={([file]) => bring(file)}
                >
                  {recording ? (
                    <Stage view={view} frame={line} unit={unit} stream={recorder.stream} />
                  ) : (
                    <LinePlayer key={playerKey} speed={speed} onSpeed={setSpeed} view={view} frame={previewLine} editingWindow={draftSize !== null} unit={unit} captions={captions} onCaptions={setCaptions} onProgress={setProgress} />
                  )}
                  {recorder.state === "count" && <span className="ep-count">{recorder.count}</span>}
                </FileDrop>
              </div>
              {!recording && chapterActions}
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
              ) : null}
              {recorder.problem && (
                <p className="ep-notice" data-tone="red" role="alert">
                  {recorder.problem}
                </p>
              )}
              {!recording && unit?.picture.status === "failed" && (
                <p className="ep-notice" data-tone="red">
                  This picture couldn't be made: {unit.picture.failure || "it stopped"}.{" "}
                  <button type="button" className="linkish" disabled={busy} onClick={() => void run(() => api.makePictures(view.id, { units: [unit.id] }))}>
                    Try again
                  </button>
                </p>
              )}
              {!recording && unit && <Stills key={unit.id} view={view} unit={unit} lines={lines} picked={line.id} onPick={pick} run={run} busy={busy} />}
              <Timeline
                view={view}
                chapter={chapter}
                lines={lines}
                current={line.id}
                playhead={playhead}
                recording={recording}
                tall
                onPick={pick}
                onJoin={(frame) => {
                  pick(frame);
                  setPanel("transition");
                }}
              />
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
            ) : null}
            {recording && choiceRail}
          </div>
        </div>
      )}
          <div className="ep-doc-grid" data-expanded={full || undefined}>
            <div className="ep-doc-main">
              <header className="ep-doc-head">
                <h1>{chapter.question}</h1>
              </header>
              <div onClickCapture={e => { if ((e.target as HTMLElement).closest(".ep-line-card,.ep-block-head")) setSelected(true); }}>
              <Script
                ref={script}
                view={view}
                chapter={chapter}
                lines={lines}
                current={line.id}
                recording={recording}
                said={recorder.index}
                solo={solo}
                take={take}
                marked={marked}
                run={run}
                busy={busy || working}
                onPick={pick}
                onOpen={(u) => {
                  if (!u.frames.includes(line.id)) pick(u.frames[0]);
                  toggleEditor(true);
                }}
                onReword={reword}
                onRecordLine={recordLine}
                onAskLine={(frame, words, text, scope) => {
                  // what was asked at the caret: about the line (or the words selected in it), the
                  // picture it shows, its chapter or the whole film
                  const n = lines.findIndex((l) => l.id === frame) + 1;
                  const [asked, label]: [EpisodeAsk, string] =
                    scope === "picture"
                      ? [{ scope, target: frame, text }, `Ch ${number} · picture of line ${n}`]
                      : scope === "chapter"
                        ? [{ scope, target: chapter.id, text }, `Chapter ${number}`]
                        : scope === "film"
                          ? [{ scope, text }, "The film"]
                          : [{ scope: "line", target: frame, text: scope === "words" && words ? `About the words “${words}”: ${text}` : text }, `Ch ${number} · line ${n}`];
                  if (working) return waiting.add({ ...asked, label });
                  void run(() => api.askEpisode(view.id, asked));
                }}
                onUndo={() => !busy && !working && view.last_change && void run(() => api.undoEpisode(view.id))}
                onRedo={() => !busy && !working && view.undone && void run(() => api.redoEpisode(view.id))}
              />
              </div>
            </div>
          </div>
        </div>
        {!recording && !full && (
          <div className="ep-doc-grid ep-doc-foot">
            <div className="ep-doc-main">
              {/* what the writer is on, what its last change did and what waits: the asking itself
                  is done at the caret */}
              <Ask bare view={view} run={run} busy={busy} waiting={waiting} marks={marks} />
              {selected && <Timeline
                view={view}
                chapter={chapter}
                lines={lines}
                current={line.id}
                recording={recording}
                onPick={(frame) => {
                  pick(frame);
                  script.current?.focusLine(frame);
                }}
                onJoin={(frame) => {
                  pick(frame);
                  setPanel("transition");
                  toggleEditor(true);
                }}
              />}
            </div>
          </div>
        )}
        {/* the frame for the line the caret is on, beside it in the editor, drawn on a canvas */}
        {!full && <aside className="ep-doc-aside" aria-label="The frame for this line">
          <div className="ep-float" style={{ top: 0 }}>
            <FileDrop
              className="ep-peek-drop"
              label={`Drop a recording of chapter ${number}`}
              refusal="A recording is a video or an audio file."
              one
              disabled={recording || busy}
              accepts={takesFile}
              onFiles={([file]) => bring(file)}
            >
              <Tooltip content="Opens the frame with its choices and the recorder" side="bottom">
                <button ref={peekRef} type="button" className="ep-peek-stage ep-float-frame" aria-label="Open the frame, its choices and the recorder" onClick={() => toggleEditor(true)}>
                  {line.presence === "person" && !previewTake?.video ? (
                    <span className="ep-chapter-poster">
                      {artwork ? <img alt={`Artwork for chapter ${number}`} src={artwork.url} /> : <b>{chapter.question}</b>}
                      <small>{artwork ? "Chapter artwork" : "Camera not recorded"}</small>
                    </span>
                  ) : <FrameCanvas view={view} frame={line} unit={unit} take={previewTake} label={`The frame for line ${at + 1}`} />}
                  <span className="ep-peek-open" aria-hidden="true">
                    <Maximize2 />
                    Open
                  </span>
                </button>
              </Tooltip>
            </FileDrop>
            <p className="ep-float-line">
              Line {at + 1} of {lines.length}
              {span ? ` · ${mmss(span.start)}–${mmss(span.start + span.seconds)}` : ""} · {LAYOUTS[line.layout] ?? line.layout}
            </p>
            {take && sayAgain > 0 && (
              <p className="ep-notice" data-tone="amber">
                {sayAgain === 1 ? "A line was" : `${sayAgain} lines were`} changed after this take: say {sayAgain === 1 ? "it" : "them"} again, or retake the chapter.
              </p>
            )}
            {view.film_state.status && <RenderStatus film={view.film_state} />}
            {view.film_state.status === "failed" && (
              <button type="button" className="linkish" disabled={busy || working || !!view.film_state.blocked} onClick={() => void run(() => api.renderEpisode(view.id))}>
                Retry render
              </button>
            )}
            {view.film_state.status === "done" && view.film_state.stale && (
              <p className="ep-notice" data-tone="amber">
                The film was rendered before your changes.{" "}
                <button type="button" className="linkish" title={view.film_state.blocked || undefined} disabled={busy || working || !!view.film_state.blocked} onClick={() => void run(() => api.renderEpisode(view.id))}>
                  Render again
                </button>
              </p>
            )}
            {pics.planned > 0 ? (
              <p className="ep-notice">Its {pics.planned === 1 ? "picture is" : `${pics.planned} pictures are`} made first.</p>
            ) : pics.making > 0 ? (
              <p className="ep-notice ep-peek-making" role="status">
                <span className="spin" />
                Making its pictures · {pics.made + pics.go} of {pics.all}
              </p>
            ) : pics.failed > 0 ? (
              <p className="ep-notice" data-tone="red">
                {pics.failed === 1 ? "A picture was" : `${pics.failed} pictures were`} not made.{" "}
                <button
                  type="button"
                  className="linkish"
                  disabled={busy}
                  onClick={() => void run(() => api.makePictures(view.id, { units: view.units.filter((u) => u.chapter === chapter.id && u.picture.status === "failed").map((u) => u.id) }))}
                >
                  Try again
                </button>
              </p>
            ) : (
              pics.changed > 0 && <p className="ep-notice">You can record now: {pics.changed === 1 ? "its picture is" : "its pictures are"} drawn again when you apply your changes.</p>
            )}
            {chapterActions}
          </div>
        </aside>}
        {full && !recording && <aside className="ep-editor-tools" aria-label="Line settings">
          <section className="ep-pop-panel">
            <ChoicePanel
              draftSize={draftSize} onDraftSize={size => setResizing(size === null ? null : {line: line.id, size})}
              panel={panel}
              view={view}
              chapter={chapter}
              line={line}
              unit={unit}
              run={run}
              busy={busy || working}
              onFilm={() => onAt(FILM)}
              onAskPicture={() => {
                askAfter.current = true;
                toggleEditor(false);
              }}
            />
          </section>
          {choiceRail}
        </aside>}
      </section>


    </main>
  );
}

// Whether the line's words are shown over the frame, kept on this computer; on until switched off.
function useCaptions(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem("episode-script-shown") !== "off";
    } catch {
      return true;
    }
  });
  const set = (to: boolean) => {
    setOn(to);
    try {
      localStorage.setItem("episode-script-shown", to ? "on" : "off");
    } catch {
      // storage is off: the switch holds for this visit
    }
  };
  return [on, set];
}

// The rail's panel a person opened last, so the next pop-up opens on it.
let lastPanel: Panel = "layout";

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
