// An episode's studio, over the channel: the plan and the studio in one place. The bar holds the
// film's title, its own choices (look, voice, pictures), where its pictures stand and, once it is
// rendered, its file. Every page is the same three columns: the film and its chapters as slides,
// a document in the middle (the whole script on the film's page, one chapter's on a chapter's),
// and the frame on the right. Words are changed where they are read; anything else is asked for
// in the change bar under the script. Recording happens in the same screen.
import { ArrowLeft, ArrowRight, ChevronLeft, ChevronRight, Circle, Maximize2, Mic, Minimize2, Moon, Pencil, Play, RotateCcw, Square, Sun, Undo2, Upload } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type EpisodeChapter, type EpisodeFrame, type EpisodeUnit, type EpisodeView, type WriterId } from "../../api";
import { chapterName, clockLine, LAYOUTS, linesOf, mmss, pictureCount, pictureState, PRESENCE, takeOf, unitOf } from "../../episode";
import { useHouse } from "../../store";
import { useTheme } from "../../theme";
import { AgentMark } from "../../ui";
import { FileDrop } from "../FileDrop";
import { Kbd } from "../Kbd";
import { Select } from "../Select";
import { Tooltip } from "../Tooltip";
import { Ask, turning, useWaiting, type AskHandle, type AskTarget, type Marks, type Run, type Waiting } from "./Ask";
import { Choices } from "./Choices";
import { Devices, Level } from "./Devices";
import { Changed } from "./Diff";
import { useRecorder, type Recording } from "./recorder";
import { BlockHead, blockName, blocksOf, type Block } from "./Blocks";
import { FilmPage, WRITERS, type Open } from "./Film";
import { agentOptions, PictureBlock, Stills } from "./Picture";
import { FILM, Slides } from "./Slides";
import { Stage, type Playing } from "./Stage";
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
  const [busy, setBusy] = useState(false);
  const go = useCallback<Open>((to, record = false, line) => {
    setRecordNext(record);
    setLineNext(line ?? null);
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
        <Chapter
          key={chapter.id}
          view={view}
          chapter={chapter}
          run={run}
          busy={busy}
          record={recordNext}
          line={lineNext}
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
  const [theme, setTheme] = useTheme();
  return (
    <div className="ep-appearance" role="group" aria-label="Appearance">
      <Tooltip content="Light" side="bottom" align="end">
        <button type="button" aria-label="Light" aria-pressed={theme === "light"} onClick={() => setTheme("light")}>
          <Sun />
        </button>
      </Tooltip>
      <Tooltip content="Dark" side="bottom" align="end">
        <button type="button" aria-label="Dark" aria-pressed={theme === "dark"} onClick={() => setTheme("dark")}>
          <Moon />
        </button>
      </Tooltip>
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

// One chapter: the script, the frame for the picked line, that line's choices.
function Chapter({
  view,
  chapter,
  run,
  busy,
  record,
  line: opening,
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
  onAt: Open;
  waiting: Waiting;
  marks: Marks;
}) {
  const plan = view.plan!;
  const lines = useMemo(() => linesOf(chapter), [chapter]);
  const number = plan.chapters.indexOf(chapter) + 1;
  const [picked, setPicked] = useState(() => (opening && lines.some((l) => l.id === opening) ? opening : lines[0].id));
  const [editing, setEditing] = useState<string | null>(null);
  const [playing, setPlaying] = useState<Playing>(null);
  // The frame, its choices and the recorder open full screen over the page. A take opens them,
  // and they stay open after it, so the take can be seen at once.
  const [full, setFull] = useState(false);
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

  const fullRef = useRef<HTMLDivElement>(null);
  const peekRef = useRef<HTMLButtonElement>(null);
  const wasFull = useRef(false);
  const askAfter = useRef(false);
  useEffect(() => {
    if (recording) setFull(true);
  }, [recording]);
  useEffect(() => {
    if (full) fullRef.current?.focus({ preventScroll: true });
    else if (askAfter.current) ask.current?.open("picture");
    else if (wasFull.current) peekRef.current?.focus({ preventScroll: true });
    askAfter.current = false;
    wasFull.current = full;
  }, [full]);
  useEffect(() => {
    if (!full || recording) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || (e.target as HTMLElement).closest("textarea, input")) return;
      e.preventDefault();
      setFull(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full, recording]);

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
      } else if (e.key === "Enter" && canEdit && !full && (on === document.body || on.classList.contains("ep-line"))) {
        e.preventDefault();
        setEditing(line.id);
      } else if (e.key === "/" && !full) {
        e.preventDefault();
        ask.current?.open();
      } else if ((e.key === "r" || e.key === "R") && !busy) {
        e.preventDefault();
        begin();
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

  const blocks = useMemo(() => blocksOf(view, lines), [lines, view]);
  const lineItem = (l: EpisodeFrame) => {
    const i = lines.indexOf(l);
    const current = l.id === line.id;
    const again = view.rerecord.includes(l.id);
    const before = marked ? was[l.id] : undefined;
    // What a rich picture does on this line, from its motion plan: on every line while the
    // picture is drawn and looked at, after that on the line that is picked.
    const mine = unitOf(view, l.id);
    const shot = mine?.picture.motion?.shots.find((s) => s.frame === l.id);
    const reviewing = mine ? ["making", "go"].includes(pictureState(mine)) : false;
    return [
      <li key={l.id}>
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
            {shot && !recording && (current || reviewing) && (
              <p className="ep-shot" title={`It ends on: ${shot.still}`}>
                {shot.shot || shot.hero}
              </p>
            )}
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
  };

  return (
    <main className="ep-chapter" data-recording={recording || undefined}>
      <Slides view={view} at={chapter.id} onAt={(id) => onAt(id)} />

      <section className="ep-doc" aria-label="Script">
        <div className="ep-doc-body">
          <header className="ep-doc-head">
            <div className="ep-doc-top">
              <p className="ep-kicker">
                Chapter {number} · {chapterName(chapter)} · {mmss(view.clock?.chapters.find((c) => c.id === chapter.id)?.seconds ?? chapter.seconds)}
              </p>
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
                    onChange={(id) => id !== view.builders[chapter.id] && void run(() => api.chooseEpisode(view.id, { builders: { [chapter.id]: id === view.settings.writer ? null : (id as WriterId) } }))}
                  />
                </label>
              )}
            </div>
            <h1>{chapter.question}</h1>
          </header>
          {marked && cuts.has("") && <ol className="ep-block-lines">{cutRows("")}</ol>}
          {blocks.map((b) =>
            b.unit ? (
              <PictureBlock
                key={b.key}
                view={view}
                block={b as Block & { unit: EpisodeUnit }}
                lines={lines}
                picked={line.id}
                onPick={pick}
                onOpen={() => {
                  if (!b.lines.some((l) => l.id === line.id)) pick(b.lines[0].id);
                  setFull(true);
                }}
                run={run}
                busy={busy || working || recording}
              >
                {b.lines.flatMap(lineItem)}
              </PictureBlock>
            ) : (
              <section key={b.key} className="ep-block" aria-label={blockName(b)}>
                <BlockHead block={b} view={view} />
                <ol className="ep-block-lines">{b.lines.flatMap(lineItem)}</ol>
              </section>
            ),
          )}
        </div>
        {!recording && <Ask ref={ask} view={view} targets={targets} run={run} busy={busy} slash waiting={waiting} marks={marks} />}
      </section>

      <aside className="ep-peek" aria-label="The frame for this line">
        <FileDrop className="ep-peek-drop" label={`Drop a recording of chapter ${number}`} refusal="A recording is a video or an audio file." one disabled={recording || busy} accepts={takesFile} onFiles={([file]) => bring(file)}>
          <Tooltip content="Opens the frame with its choices and the recorder" side="bottom">
            <button ref={peekRef} type="button" className="ep-peek-stage" aria-label="Open the frame, its choices and the recorder" onClick={() => setFull(true)}>
              {full ? <span className="ep-peek-blank" /> : <Stage view={view} frame={line} unit={unit} take={take} small />}
              <span className="ep-peek-open" aria-hidden="true">
                <Maximize2 />
                Open
              </span>
            </button>
          </Tooltip>
        </FileDrop>
        <p className="ep-peek-line">
          Line {at + 1} of {lines.length} · {LAYOUTS[line.layout] ?? line.layout}
        </p>
        <div className="ep-peek-actions">
          <Tooltip content={pics.planned ? "Makes this chapter's pictures first" : "Opens the camera and microphone"} shortcut="R" side="bottom">
            <button type="button" className={`btn ${take ? "" : "primary"}`} disabled={busy || (waits > 0 && pics.planned === 0)} onClick={begin}>
              <Circle />
              {take ? "Retake" : `Record chapter ${number}`}
            </button>
          </Tooltip>
          {onward}
        </div>
        {take && (
          <small className="ep-peek-take">
            Take {take.n} · {mmss(take.seconds)}
          </small>
        )}
        {pics.planned > 0 ? (
          <p className="ep-notice">
            Its {pics.planned === 1 ? "picture is" : `${pics.planned} pictures are`} made first.
          </p>
        ) : pics.making > 0 ? (
          <p className="ep-notice ep-peek-making" role="status">
            <span className="spin" />
            Making its pictures · {pics.made + pics.go} of {pics.all}
          </p>
        ) : pics.failed > 0 ? (
          <p className="ep-notice" data-tone="red">
            {pics.failed === 1 ? "A picture was" : `${pics.failed} pictures were`} not made.{" "}
            <button type="button" className="linkish" disabled={busy} onClick={() => void run(() => api.makePictures(view.id, { units: view.units.filter((u) => u.chapter === chapter.id && u.picture.status === "failed").map((u) => u.id) }))}>
              Try again
            </button>
          </p>
        ) : (
          pics.changed > 0 && (
            <p className="ep-notice">You can record now: {pics.changed === 1 ? "its picture is" : "its pictures are"} drawn again when you apply your changes.</p>
          )
        )}
      </aside>

      {full && (
        <div ref={fullRef} className="ep-full" role="dialog" aria-modal="true" aria-label={`Chapter ${number}: the frame, its choices and the recorder`} tabIndex={-1} data-recording={recording || undefined}>
          <header className="ep-full-head">
            <b>Chapter {number}</b>
            <span>{chapterName(chapter)}</span>
            <span className="ep-gap" />
            {!recording && (
              <Tooltip content="Back to the script" shortcut="Esc" side="bottom" align="end">
                <button type="button" className="icon-btn" aria-label="Back to the script" onClick={() => setFull(false)}>
                  <Minimize2 />
                </button>
              </Tooltip>
            )}
          </header>
          <div className="ep-full-body">
            <section className="ep-middle">
              <FileDrop
                className="ep-stage-wrap"
                label={`Drop a recording of chapter ${number}`}
                refusal="A recording is a video or an audio file."
                one
                disabled={recording || busy}
                accepts={takesFile}
                onFiles={([file]) => bring(file)}
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
                  <Tooltip content={pics.planned ? "Makes this chapter's pictures first" : "Opens the camera and microphone"} shortcut="R" side="top">
                    <button type="button" className={`btn ${take ? "" : "primary"}`} disabled={busy || (waits > 0 && pics.planned === 0)} onClick={begin}>
                      <Circle />
                      {take ? "Retake" : `Record chapter ${number}`}
                    </button>
                  </Tooltip>
                  {onward}
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
                </div>
              )}
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
              {!recording && unit && <Stills view={view} unit={unit} lines={lines} picked={line.id} onPick={pick} run={run} busy={busy} />}
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
              <Choices view={view} chapter={chapter} line={line} unit={unit} run={run} busy={busy || working} onFilm={() => onAt(FILM)} onAskPicture={() => {
                    askAfter.current = true;
                    setFull(false);
                  }}
                />
            )}
          </div>
        </div>
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
