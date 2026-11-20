// An episode's studio, over the channel: the plan and the studio in one place. The bar holds the
// film's choices (look, voice, pictures), where its pictures stand and, once it is
// rendered, its file. Every page is the same three columns: the film and its chapters as slides,
// a document in the middle (the whole script on the film's page, one chapter's on a chapter's),
// and the frame on the right. Words are changed where they are read; anything else is asked for
// at the caret, about the line, its picture, the chapter or the film (the film's page keeps a
// change bar of its own). Recording happens in the same screen.
import { isWorkspaceTarget } from "../workspaceTarget";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Circle,
  Headphones,
  Mic,
  ListVideo,
  Maximize2,
  Minimize2,
  Monitor,
  Moon,
  Play,
  Sparkles,
  Sun,
} from "lucide-react";
import { flushSync } from "react-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type EpisodeAsk, type EpisodeChapter, type EpisodeView } from "../../api";
import { asVersion, chapterName, clockLine, LAYOUTS, linesOf, mmss, pictureCount, resizePresenter, takeOf, turning, unitOf, versionShown } from "../../episode";
import { useHouse } from "../../store";
import { useTheme } from "../../theme";
import { FileDrop } from "../FileDrop";
import { Kbd } from "../Kbd";
import { Select } from "../Select";
import { Tooltip } from "../Tooltip";
import { Ask, useWaiting, type Marks, type Run, type Waiting } from "./Ask";
import { ChoicePanel, PANELS, type Panel } from "./Choices";
import { Devices, Level } from "./Devices";
import { useNarrationGuide } from "./narrationGuide";
import { useRecorder, type Recording } from "./recorder";
import { RecordingScript } from "./RecordingScript";
import { CameraFile, ImportLine, TakeOrigin } from "./CameraFile";
import { TakeReviewDetails } from "./TakeReviewDetails";
import { FilmPage, type Open } from "./Film";
import { Script, type ScriptHandle } from "./Script";
import { PictureHead, Stills } from "./Picture";
import { RegenerateChapter } from "./RegenerateChapter";
import { FILM, Slides } from "./Slides";
import { LinePlayer } from "./LinePlayer";
import { FrameCanvas } from "./FrameCanvas";
import { spanAt } from "./chapterSeek";
import { spansOf, Timeline } from "./Timeline";
import { Stage } from "./Stage";
import { ApplyChanges, FilmDownload, FilmTools } from "./Tools";
import { RunningPill } from "./Running";
import { VersionChip, type Seen } from "./Versions";
import { WorkPill } from "./Work";
import { PlanRun } from "./PlanRun";

export function EpisodeStudio() {
  const view = useHouse((s) => s.episode);
  const openEpisode = useHouse((s) => s.openEpisode);
  // opened as a peek, it sits over the page it was opened from, which Escape goes back to
  const peek = useHouse((s) => s.episodePeek);
  const landing = useHouse((s) => s.landing);
  const [at, setAt] = useState<string>(FILM);
  // The chapter that opens next is to be recorded at once: the run-through, once the choices are
  // made. It opens at a line when one was picked on the film's page.
  const [recordNext, setRecordNext] = useState(false);
  const [lineNext, setLineNext] = useState<string | null>(null);
  // the frame's pop-up stays open when the carousel moves it to another chapter
  const [popNext, setPopNext] = useState(false);
  const [busy, setBusy] = useState(false);
  // counts the times a place was asked for, so a chapter already open goes to the line asked for
  const [asked, setAsked] = useState(0);
  const go = useCallback<Open>((to, record = false, line, pop = false) => {
    setRecordNext(record);
    setLineNext(line ?? null);
    setPopNext(pop);
    setAt(to);
    setAsked((n) => n + 1);
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
  // A link or the board asked for a chapter, at a line: it opens there once, as soon as the plan
  // is in. The chapter it is on is said back, so the address names it.
  const planned = Boolean(view?.plan) && view?.status !== "planning" && view?.status !== "failed";
  useEffect(() => {
    if (!landing || !planned || !view?.plan) return;
    if (view.plan.chapters.some((c) => c.id === landing.chapter)) go(landing.chapter, false, landing.line || undefined);
    useHouse.setState({ landing: null });
  }, [landing, planned, view?.plan, go]);
  useEffect(() => {
    useHouse.setState({ episodeChapter: at === FILM ? "" : at });
  }, [at]);
  // The whole page, from a peek: its channel comes to the front, and Back leads to the board.
  const whole = useCallback(() => {
    if (!view) return;
    useHouse.setState({ episodePeek: false });
    void useHouse.getState().openChannel(view.channel_id, "canvas");
  }, [view]);
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
      if (e.key !== "Escape" || (e.target !== document.body && !isWorkspaceTarget(e.target)) || e.defaultPrevented || document.querySelector(".ep-full")) return;
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
      if ((e.target as HTMLElement).closest("textarea, input, [contenteditable]") || document.querySelector(".ep-chapter-sheet[data-recording]")) return;
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
      <>
        {peek && <div className="ep-scrim" aria-hidden="true" onClick={() => void openEpisode(null)} />}
        <div className="ep" data-peek={peek || undefined} role="dialog" aria-modal="true" aria-label="Episode">
          <div className="ep-wait">
            <span className="spin" />
          </div>
        </div>
      </>
    );
  }
  const plan = view.plan;
  const chapter = plan?.chapters.find((c) => c.id === at);
  const ready = plan !== null && view.status !== "planning" && view.status !== "failed";
  return (
    <>
      {peek && <div className="ep-scrim" aria-hidden="true" onClick={() => void openEpisode(null)} />}
      <div className="ep" data-peek={peek || undefined} role="dialog" aria-modal="true" aria-label={`Episode: ${view.title}`}>
        <Bar view={view} ready={ready} onAt={go} onClose={() => void openEpisode(null)} onWhole={peek ? whole : undefined} run={run} busy={busy} />
        {!ready || !plan ? (
          <PlanRun view={view} run={run} busy={busy} />
        ) : (
          <main className={chapter ? "ep-chapter" : "ep-chapter ep-film-page"}>
            <Slides view={view} at={chapter?.id ?? FILM} onAt={go} />
            {chapter ? (
              <Chapter key={chapter.id} view={view} chapter={chapter} run={run} busy={busy} record={recordNext} line={lineNext} pop={popNext} asked={asked} onAt={go} waiting={waiting} marks={marks} />
            ) : <FilmPage view={view} run={run} busy={busy} onAt={go} waiting={waiting} />}
          </main>
        )}
      </div>
    </>
  );
}

// The way back to the canvas, the film's choices, what runs now, its picture status, and light
// or dark. The slides under it are the way between the film and its chapters.
// `onWhole` is there for an episode open as a peek: Back returns to the page under it, and the
// whole page is one press away.
function Bar({ view, ready, onAt, onClose, onWhole, run, busy }: { view: EpisodeView; ready: boolean; onAt: Open; onClose: () => void; onWhole?: () => void; run: Run; busy: boolean }) {
  const back = onWhole ? "Back to the board" : "Back to the canvas";
  return (
    <header className="ep-bar">
      <Tooltip content={back} shortcut="Esc" side="bottom" align="start">
        <button type="button" className="btn ep-back" aria-label={back} onClick={onClose}>
          <ArrowLeft /> Back
        </button>
      </Tooltip>
      {onWhole && (
        <Tooltip content="Open the episode's own page" side="bottom" align="start">
          <button type="button" className="btn ep-back" onClick={onWhole}>
            <Maximize2 /> Open full page
          </button>
        </Tooltip>
      )}
      {ready && <FilmTools view={view} run={run} busy={busy} />}
      <span className="ep-gap" />
      {ready && <Now view={view} run={run} busy={busy} onAt={onAt} />}
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

// What runs now, where the pictures stand, the changes that wait to be applied, and the way to
// make the pictures nobody asked for yet: all of them at once, or the rest once some were made a
// chapter or a picture at a time. Once the plan is approved, applying the changes makes the new
// ones too.
function Now({ view, run, busy, onAt }: { view: EpisodeView; run: Run; busy: boolean; onAt: Open }) {
  const pictures = pictureCount(view);
  const asked = pictures.all - pictures.planned;
  const first = asked === 0 && view.waiting.length === 0;
  return (
    <div className="ep-now">
      <RunningPill view={view} onAt={onAt} />
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
  asked,
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
  // counts the times a place was asked for: this chapter asked for again goes to that line
  asked: number;
  onAt: Open;
  waiting: Waiting;
  marks: Marks;
}) {
  const plan = view.plan!;
  const lines = useMemo(() => linesOf(chapter), [chapter]);
  const voice = view.settings.voice;
  const missingVoice = voice === "local" || voice === "narrator" ? lines.filter(line => {
    const clock = clockLine(view, line.id);
    return line.vo.trim() && clock && clock.source.kind !== "take" && !clock.audio_url;
  }).map(line => line.id + "/" + line.vo).join("\n") : "";
  useEffect(() => {
    if (voice !== "local" || !missingVoice) return;
    let active = true;
    api.previewVoice(view.id, chapter.id).then(next => {
      if (active) useHouse.getState().setEpisode(next);
    }).catch(error => { if (active) useHouse.getState().say(error.message); });
    return () => { active = false; };
  }, [view.id, chapter.id, voice, missingVoice]);
  const number = plan.chapters.indexOf(chapter) + 1;
  const [picked, setPicked] = useState(() => (opening && lines.some((l) => l.id === opening) ? opening : lines[0].id));
  const [progress, setProgress] = useState<number | null>(null);
  const [captions, setCaptions] = useCaptions();
  // The editor expands above the script; recording uses the full workspace.
  const [full, setFull] = useState(pop);
  const [selected, setSelected] = useState(Boolean(opening || pop));
  const [timelineVisible, setTimelineVisible] = useState(true);
  const [chapterRun, setChapterRun] = useState(0);
  const [chapterCue, setChapterCue] = useState<{ offset: number; play: boolean } | null>(
    pop && !opening ? {offset: 0, play: false} : null
  );
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
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
  const script = useRef<ScriptHandle>(null);
  const take = takeOf(view, chapter.id);
  const sayAgain = lines.filter((l) => view.rerecord.includes(l.id)).length;
  const presenterOff = view.settings.presenter === "off";
  const working = turning(view);

  const [takeLabel, setTakeLabel] = useState("");
  const save = useCallback(
    async (recording: Recording) => {
      const saved = await run(() => api.addTake(view.id, { chapter: chapter.id, frame: solo ?? undefined, marks: recording.marks, file: recording.blob, name: recording.name, label: takeLabel, startedAt: recording.startedAt }));
      if (!saved) throw new Error("The take could not be saved. Please try again.");
      setSolo(null);
      setTakeLabel("");
    },
    [run, view.id, chapter.id, solo, takeLabel],
  );
  const frames = useMemo(() => (solo ? [solo] : lines.map((l) => l.id)), [solo, lines]);
  const recorder = useRecorder({ frames, camera: !presenterOff, onDone: save });
  const recording = recorder.state !== "off";
  const guide = useNarrationGuide();
  const [guided, setGuided] = useState(voice === "narrator" || voice === "local");
  const [guideDuration, setGuideDuration] = useState(0);
  const [preparing, setPreparing] = useState(false);
  const startRecording = async () => {
    if (preparing || guide.loading) return;
    if (!guided) return recorder.start();
    setPreparing(true);
    try {
      let prepared = view;
      if (frames.some(id => !clockLine(prepared, id)?.audio_url)) {
        prepared = await api.previewVoice(view.id, chapter.id);
        useHouse.getState().setEpisode(prepared);
      }
      const urls = frames.map(id => clockLine(prepared, id)?.audio_url);
      if (urls.some(url => !url)) throw new Error("Narration is unavailable. Turn off Follow narration to record your voice.");
      const narration = await guide.prepare(urls as string[]);
      if (narration) {
        setGuideDuration(narration.durations.reduce((sum, duration) => sum + duration, 0));
        recorder.start(narration);
      }
    } catch (error) { useHouse.getState().say((error as Error).message); }
    finally { setPreparing(false); }
  };
  const said = solo ? lines.find((l) => l.id === solo) : lines[recorder.index];
  const line = (recording && recorder.state !== "saving" ? said : undefined) ?? lines.find((l) => l.id === picked) ?? lines[0];
  const unit = unitOf(view, line.id);
  // A version of the line's picture picked to look back at, which the frame shows in place of the
  // latest while that picture's lines are open. With none picked, a picture being made again
  // shows the version it was until then, which plays on while the new one is made.
  const [seen, setSeen] = useState<Seen>(null);
  const seenUnit = unit?.id;
  useEffect(() => setSeen((was) => (was && was.unit !== seenUnit ? null : was)), [seenUnit]);
  const lookedAt = seen && unit && seen.unit === unit.id && unit.picture.versions.some((v) => v.n === seen.n) ? seen.n : null;
  const version = unit?.kind === "picture" ? versionShown(unit, lookedAt, view) : undefined;
  const shown = unit && version ? asVersion(unit, version) : unit;
  const at = lines.indexOf(line);
  const scheduled = clockLine(view, line.id);
  const [resizing, setResizing] = useState<{line: string; size: number} | null>(null);
  const draftSize = resizing?.line === line.id ? resizing.size : null;
  const previewLine = draftSize === null ? line : resizePresenter(view, line, draftSize);
  const playerKey = [line.id, view.film_state.stale, view.film_state.file?.id, view.settings.voice, shown?.picture.clip?.id, version?.n, scheduled?.audio_url, scheduled?.source.take].join("/");
  const following = plan.chapters[number];
  const previous = number > 1 ? plan.chapters[number - 2] : undefined;
  // How long the take was planned to run: the chapter, or the one line said again.
  const planned = solo ? (lines.find((l) => l.id === solo)?.seconds ?? 0) : (view.clock?.chapters.find((c) => c.id === chapter.id)?.seconds ?? chapter.seconds);
  // What the last change did is marked in the script, except while a take is recorded.
  const marked = marks.on && !recording;
  // A line picked to be said again: the recorder is armed once it knows it has one line.
  const arm = recorder.arm;
  // A chapter is said over its pictures, so they are made before it is recorded. Asking to
  // record a chapter whose pictures nobody asked for yet makes them; the camera opens once
  // none is still on its way.
  const pics = pictureCount(view, chapter.id);
  const waits = pics.planned + pics.making;
  const episode = view.id;
  const begin = useCallback(() => {
    setChapterCue(null);
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
      if (e.repeat || (e.target as HTMLElement).closest("button, input, select, textarea, [role=combobox]")) return;
      if (recorder.state === "ready") {
        if (e.key !== " ") return;
        e.preventDefault();
        void startRecording();
      } else if (e.key === " " || e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        if (!guided) recorder.next();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [recorder, guided, startRecording]);

  const { spans, total } = spansOf(view, chapter, lines);
  const span = spans.find((x) => x.line.id === line.id);
  const playhead = recording ? (solo ? (span?.start ?? 0) : 0) + recorder.elapsed : span && progress !== null ? span.start + progress * span.seconds : null;
  const pick = (frame: string) => {
    setChapterCue(null);
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
    if (!open) setChapterCue(null);
    // a version looked back at is the editor's: put away, the chapter shows its pictures as they stand
    if (!open) setSeen(null);
    if (open) scriptScroll.current = scrollerOf(scriptBody.current)?.scrollTop ?? 0;
    const source = open ? peekRef.current : fullRef.current?.querySelector<HTMLElement>(".ep-pop-stage");
    const from = source?.getBoundingClientRect();
    const update = () => {
      flushSync(() => { setFull(open); setSelected(open); });
      // what scrolls the script depends on the window's size: opened, the editor at its head is
      // brought into view from wherever the script was; put away, the script is where it was
      const scroller = scrollerOf(scriptBody.current);
      if (!scroller) return;
      if (!open) scroller.scrollTop = scriptScroll.current;
      else if (fullRef.current) scroller.scrollTop += fullRef.current.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
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
  // Asked for again while it is open (a task opened from the bar): the line asked for is picked
  // and, where its frame was asked for too, the editor opens on it.
  const askedAt = useRef(asked);
  useEffect(() => {
    if (askedAt.current === asked) return;
    askedAt.current = asked;
    if (recording) return;
    if (opening && lines.some((l) => l.id === opening)) pick(opening);
    if (pop && !full) toggleEditor(true);
  }, [asked]);
  useEffect(() => {
    if (!full || recording) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || (e.target !== document.body && !isWorkspaceTarget(e.target)) || e.defaultPrevented || (e.target as HTMLElement).closest("textarea, input")) return;
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
  // a take recorded here can be matched to the camera's own file of it; one that is a file already can't
  const studioTake = take && take.recording.kind !== "camera" && take.recording.kind !== "file" ? take : undefined;
  const coming = view.imports.some((i) => i.chapter === chapter.id && i.state !== "failed");
  const takeLines = <><ImportLine view={view} chapter={chapter.id} run={run} /><TakeOrigin view={view} take={take} run={run} busy={busy} /></>;
  const previewTake = scheduled?.source.kind === "take" ? view.takes.find(t => t.id === scheduled.source.take) : undefined;
  const artwork = view.units.filter(u => u.chapter === chapter.id).flatMap(u => Object.values(u.picture.stills))[0];
  const chapterPoster = (
    <span className="ep-chapter-poster">
      {artwork ? <img alt={`Artwork for chapter ${number}`} src={artwork.url} /> : <b>{chapter.question}</b>}
    </span>
  );
  const cameraPoster = artwork && line.presence === "person" && !previewTake?.video ? chapterPoster : null;
  const seekChapter = (time: number, play: boolean) => {
    const target = spanAt(spans, time);
    if (!target) return;
    const offset = Math.max(0, Math.min(target.seconds, time - target.start));
    setPicked(target.line.id);
    setProgress(offset / target.seconds);
    setChapterCue({ offset, play: play && time < total });
    setChapterRun(run => run + 1);
  };
  const startChapter = async () => {
    if (voice === "narrator" && missingVoice && !await run(() => api.previewVoice(view.id, chapter.id))) return;
    seekChapter(0, true);
    if (!full) toggleEditor(true);
  };
  const playChapter = <button className="btn" type="button" disabled={recording || busy} onClick={() => void startChapter()}><Play />Play chapter</button>;
  const askChapter = <>
        <Tooltip content="Asks the writer for a change, at the caret" shortcut={ASK_KEYS} side="bottom" align="end">
          <button type="button" className="btn" disabled={recording} onClick={() => script.current?.askAt(line.id, "chapter")}>
            <Sparkles />
            Ask AI
          </button>
        </Tooltip>
  </>;
  const regenerateChapter = pics.all > 0 && <RegenerateChapter view={view} chapter={chapter.id} count={pics.all}
    disabled={busy || recording || working || pics.making > 0 || view.film_state.status === "rendering"} run={run} />;
  const chapterActions = (
    <div className="ep-doc-top">
      {full ? (
        <button type="button" className="btn ep-timeline-toggle" aria-expanded={timelineVisible}
          onClick={() => setTimelineVisible(!timelineVisible)}>
          <ListVideo aria-hidden="true" />{timelineVisible ? "Hide timeline" : "Show timeline"}
        </button>
      ) : <p className="ep-kicker">Chapter {number} · {chapterName(chapter)} · {mmss(total)}</p>}
      <div className="ep-doc-actions">
        {take && (
          <small className="ep-peek-take">
            {take.label || `Take ${take.n}`} · {mmss(take.seconds)}
          </small>
        )}
        {studioTake && <CameraFile view={view} chapter={chapter.id} guide={studioTake} run={run} disabled={busy || coming} />}
        <Tooltip content={pics.planned ? "Makes this chapter's pictures first" : "Opens the camera and microphone"} shortcut="R" side="bottom" align="end">
          <button type="button" className="btn primary ep-record-chapter" disabled={busy || (waits > 0 && pics.planned === 0)} onClick={begin}>
            <Circle />
            {take ? "Retake" : `Record chapter ${number}`}
          </button>
        </Tooltip>
        {askChapter}
        {full ? regenerateChapter : regenerateChapter && <details className="ep-chapter-more"><summary>More actions</summary><div>{regenerateChapter}</div></details>}
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
      <section data-recording={recording || undefined}
            data-review={Boolean(recorder.reviewUrl) || undefined} className="ep-doc ep-chapter-sheet" aria-label="Script">
        <div className="ep-doc-body" ref={scriptBody}>
      {full && (
        <div className={recording ? "ep-record-page" : undefined}>
          <div
            ref={fullRef}
            className={recording ? "ep-full ep-pop" : "ep-full ep-pop ep-inline-player"}
            role="region"
            aria-label={`Chapter ${number}: the frame, its choices and the recorder`}
            tabIndex={-1}
            data-recording={recording || undefined}
            data-review={Boolean(recorder.reviewUrl) || undefined}
          >
            <section className="ep-pop-main">
              <header className="ep-pop-head">
                <b>Chapter {number}</b>
                <span className="ep-chapter-kind">{chapterName(chapter)}</span>
                <small>{mmss(total)}</small>
                {!recording && unit?.kind === "picture" && <PictureHead view={view} unit={unit} run={run} busy={busy || working} recording={recording} />}
                <span className="ep-gap" />
                {!recording && <div className="ep-preview-actions"><FilmDownload view={view} />
                  <CameraFile icon view={view} chapter={chapter.id} run={run} disabled={busy || coming} />
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
                  {recorder.reviewUrl ? (
                    presenterOff
                      ? <audio className="ep-take-review" aria-label="Review your recording" controls src={recorder.reviewUrl} />
                      : <video className="ep-take-review" aria-label="Review your recording" controls playsInline src={recorder.reviewUrl} />
                  ) : recording ? (
                    <Stage view={view} frame={line} unit={shown} stream={recorder.stream} previewAt={recorder.state === "recording" ? recorder.lineElapsed : 0} />
                  ) : (
                    <LinePlayer cameraPoster={cameraPoster} key={playerKey + "/" + chapterRun} initialPosition={chapterCue?.offset} autoStart={chapterCue?.play}
                      chapter={chapterCue && span ? {start: span.start, nextStart: spans[at + 1]?.start, total, seek: seekChapter} : undefined} audioControls={{volume, setVolume, muted, setMuted}}
                      onFinish={() => {
                        if (chapterCue && spans[at + 1]) seekChapter(spans[at + 1].start, true);
                      }} speed={speed} onSpeed={setSpeed} view={view} frame={previewLine} editingWindow={draftSize !== null} unit={shown} draft={Boolean(version)} captions={captions} onCaptions={setCaptions} onProgress={setProgress} />
                  )}
                  {/* a version picked to look back at is named over the frame's corner, with the way back */}
                  {!recording && unit && version && lookedAt !== null && <VersionChip n={version.n} standing={versionShown(unit, null, view)?.n ?? unit.picture.version} onBack={() => setSeen(null)} />}
                  {recorder.state === "count" && <div className="ep-count" role="status" aria-live="assertive"><span>Recording in</span><div key={Math.max(1, recorder.count)} className="ep-count-dial"><svg viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="46" /></svg><b>{Math.max(1, recorder.count)}</b></div></div>}
                </FileDrop>
              </div>
              {!recording && chapterActions}
              {!recording && takeLines}
              {recording && !recorder.reviewUrl ? (
                <div className="ep-recbar" data-recording>
                  {recorder.state === "asking" && (
                    <span className="ep-said">
                      <span className="spin" />
                      Waiting for the camera and microphone
                    </span>
                  )}
                  {recorder.state === "ready" && (
                    <>
                      <button type="button" className="btn primary" disabled={preparing || guide.loading} onClick={() => void startRecording()}>
                        <Circle />
                        {preparing || guide.loading ? "Preparing narration…" : "Start recording"}
                        <Kbd keys="space" size="sm" />
                      </button>
                      <Devices stream={recorder.stream} devices={recorder.devices} using={recorder.using} camera={!presenterOff} onChoose={recorder.choose} />
                      {(voice === "narrator" || voice === "local") && <Select className="ep-record-mode" size="lg" aria-label="Recording audio" disabled={preparing || guide.loading} value={guided ? "narration" : "microphone"} onChange={value => setGuided(value === "narration")} options={[
                        {value: "narration", label: "Follow narration", icon: <Headphones />},
                        {value: "microphone", label: "Record microphone", icon: <Mic />},
                      ]} />}
                    </>
                  )}
                  {recorder.state === "count" && <span className="ep-said">Get ready</span>}
                  {recorder.state === "recording" && (
                    <>
                      <span className="ep-live-dot" />
                      <b className="ep-timer">{mmss(recorder.elapsed)}</b>
                      {planned > 0 && (
                        <span className="ep-planned" data-over={recorder.elapsed > planned * 1.25 || undefined}>
                          / {mmss(guided ? guideDuration : planned)}
                        </span>
                      )}
                      <Level stream={recorder.stream} />
                      <button type="button" className="btn primary" onClick={() => guided ? recorder.stop(true) : recorder.next()}>
                        {guided ? "Finish early" : solo || recorder.index + 1 >= lines.length ? "Finish" : "Next line"}
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

                </div>
              ) : null}
              {guide.problem && <p role="alert" className="ep-notice">{guide.problem}</p>}
              {recorder.problem && !recorder.reviewUrl && (
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
              {/* a redo that did not land: the version before stands again, and the beat says why */}
              {!recording && unit && (unit.picture.status === "made" || unit.picture.status === "go") && unit.picture.failure && (
                <p className="ep-notice" data-tone="amber">
                  The new version couldn't be made: {unit.picture.failure.replace(/\.+$/, "")}. Version {unit.picture.version} stands.{" "}
                  <button type="button" className="linkish" disabled={busy} onClick={() => void run(() => api.makePictures(view.id, { units: [unit.id], level: unit.level }))}>
                    Try again
                  </button>
                </p>
              )}
              {!recording && unit && <Stills key={unit.id} view={view} unit={unit} lines={lines} picked={line.id} onPick={pick} run={run} busy={busy} />}
              {!recorder.reviewUrl && (recording || timelineVisible) && <Timeline
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
              />}
            </section>
            {recording ? (
              <section className={`ep-say${recorder.reviewUrl ? " ep-review-panel" : ""}`} aria-label={recorder.reviewUrl ? "Take review" : "Say it"}>
                <button className="btn ep-record-back" type="button" disabled={preparing || guide.loading || recorder.state === "saving"} onClick={() => {
                  if ((recorder.state !== "recording" && recorder.state !== "review") || window.confirm("Discard this recording and return to the chapter?")) recorder.stop(false);
                }}>Back to chapter</button>
                {recorder.reviewUrl ? <TakeReviewDetails title={chapter.question} seconds={recorder.elapsed} video={!presenterOff}
                  lines={solo ? [line] : lines} label={takeLabel} onLabel={setTakeLabel} saving={recorder.state === "saving"}
                  problem={recorder.problem} onSave={() => void recorder.save()}
                  onAgain={() => { if (window.confirm("Discard this take and record again?")) void recorder.arm(); }} /> : <>
                <header>
                  <p className="ep-kicker">{solo ? `Say it again · line ${at + 1}` : `Say it · line ${Math.min(recorder.index + 1, lines.length)} of ${lines.length}`}</p>
                </header>
                <RecordingScript lines={lines} current={line.id} elapsed={recorder.lineElapsed} seconds={clockLine(view, line.id)?.seconds ?? line.seconds} />
                </>}
              </section>
            ) : null}

          </div>
        </div>
      )}
          <div className="ep-doc-grid" data-expanded={full || undefined}>
            <div className="ep-doc-main">
              <header className="ep-doc-head ep-chapter-heading">
                <p className="ep-chapter-meta">Chapter {number} · {chapter.beats.length} {chapter.beats.length === 1 ? "beat" : "beats"}</p>
                <h1>{chapter.question}</h1>
                {!full && playChapter}
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
        {!full && <aside className="ep-doc-aside" aria-label={selected ? "The frame for this line" : "Chapter preview"}>
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
              <Tooltip content={selected ? "Opens the frame with its choices and the recorder" : "Play every beat in this chapter"} side="bottom">
                <button ref={peekRef} type="button" className="ep-peek-stage ep-float-frame"
                  aria-label={selected ? "Open the frame, its choices and the recorder" : `Play chapter ${number}`}
                  disabled={!selected && busy}
                  onClick={selected ? () => toggleEditor(true) : () => void startChapter()}>
                  {selected
                    ? cameraPoster ?? <FrameCanvas view={view} frame={line} unit={unit} take={previewTake} label={`The frame for line ${at + 1}`} />
                    : chapterPoster}
                  <span className="ep-peek-open" data-chapter={!selected || undefined} aria-hidden="true">
                    {selected ? <><Maximize2 />Open</> : <><Play />Play chapter</>}
                  </span>
                </button>
              </Tooltip>
            </FileDrop>
            {chapterActions}
            {takeLines}
            {selected && <p className="ep-float-line">
              Line {at + 1} of {lines.length}
              {span ? ` · ${mmss(span.start)}–${mmss(span.start + span.seconds)}` : ""} · {LAYOUTS[line.layout] ?? line.layout}
            </p>}
            {take && sayAgain > 0 && (
              <p className="ep-notice" data-tone="amber">
                {sayAgain === 1 ? "A line was" : `${sayAgain} lines were`} changed after this take: say {sayAgain === 1 ? "it" : "them"} again, or retake the chapter.
              </p>
            )}
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
              onAskPicture={() => {
                askAfter.current = true;
                toggleEditor(false);
              }}
              shownVersion={lookedAt}
              onShow={(of, n, frame) => {
                if (of !== unit?.id) pick(frame);
                setSeen(n === null ? null : { unit: of, n });
              }}
            />
          </section>
          {choiceRail}
        </aside>}
      </section>
  );
}

// Whether the line's words are shown over the frame, kept on this computer; on until switched off.
// What scrolls a chapter's script: its own body where that scrolls, else the nearest box around
// it that does, since the page's layout moves it with the window's size.
function scrollerOf(at: HTMLElement | null): HTMLElement | null {
  for (; at; at = at.parentElement) {
    const { overflowY } = getComputedStyle(at);
    if ((overflowY === "auto" || overflowY === "scroll") && at.scrollHeight > at.clientHeight) return at;
  }
  return null;
}

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
