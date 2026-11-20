// The film's page, laid out as a chapter's page is: the film and its chapters as slides down the
// left, the whole script in the middle as one document, chapter by chapter in the blocks a
// chapter reads in, and the film on the right with what to do next under it. Pointing at a line
// shows its frame on the right and a click keeps it there; the frame, a double click, Enter or a
// chapter's question opens the chapter. Recording the next chapter starts here too: it opens
// the chapter, which makes its pictures first when they are not made. The film's own choices
// (look, voice, pictures) are in the bar, so they are at hand on every page.
import { ArrowRight, Circle, Clapperboard } from "lucide-react";
import { useMemo, useState } from "react";
import { api, type EpisodeChapter, type EpisodeView, type FilmSize } from "../../api";
import { chapterMaking, chapterName, chapterState, LAYOUTS, linesOf, mmss, pictureCount, STATE_WORDS, takeOf, unitOf } from "../../episode";
import { AgentMark } from "../../ui";
import { SegmentedControl } from "../SegmentedControl";
import { Tooltip } from "../Tooltip";
import { Ask, Elapsed, type AskTarget, type Run, type Waiting } from "./Ask";
import { BlockHead, blockName, blocksOf } from "./Blocks";
import { FrameCanvas } from "./FrameCanvas";
import { WorkingMark } from "./Slides";

export const RENDER_PHASES: Record<string, string> = {
  prepare: "Preparing film", compile: "Preparing scenes", start_browsers: "Starting renderer",
  extract_video: "Reading source video",
  prepare_audio: "Preparing audio", capture: "Capturing frames", encode: "Encoding video",
  mux: "Combining video and audio", finalize: "Finishing export",
};

export function RenderStatus({ film }: { film: EpisodeView["film_state"] }) {
  const running = film.status === "rendering";
  const stopped = film.status === "failed";
  const percent = Math.round(100 * (film.fraction ?? 0));
  const phase = (RENDER_PHASES[film.phase ?? ""] ?? "Rendering film") + (film.making === "4k" ? " in 4K" : "");
  return (
    <section className="ep-render-status" aria-label="Film export" data-failed={stopped || undefined}>
      <div className="ep-render-heading">
        <strong role="status">{running ? phase : stopped ? "Render stopped" : "Render complete"}</strong>
        {running && <span>{percent}%</span>}
      </div>
      {running && <progress aria-label="Overall render progress" max={100} value={percent} />}
      {running && film.phase === "capture" && film.frames_done != null && film.frames_total != null && (
        <span>{film.frames_done.toLocaleString()} of {film.frames_total.toLocaleString()} frames</span>
      )}
      {stopped && <span>{film.failure || "Retry the render."}</span>}
      {film.started_at != null && (running || film.ended_at != null) && (
        <span>{running ? "Elapsed" : stopped ? "Stopped after" : "Rendered in"}{" "}
          {running ? <Elapsed since={film.started_at} accessible /> : mmss(Math.max(0, film.ended_at! - film.started_at))}
        </span>
      )}
    </section>
  );
}

export const WRITERS: Record<string, string> = { claude: "Claude Code", codex: "Codex", kimi: "Kimi Code", builtin: "the built-in agent", demo: "the demo's writer" };
// An agent's name where it starts a line.
export const writerTitle = (id: string) => {
  const name = WRITERS[id] ?? id;
  return name.slice(0, 1).toUpperCase() + name.slice(1);
};

// Opens the film or a chapter: to be recorded at once, at a line, or with the frame's pop-up open.
export type Open = (to: string, record?: boolean, line?: string, pop?: boolean) => void;
type Spot = { chapter: string; line: string };

export function FilmPage({ view, run, busy, onAt, waiting }: { view: EpisodeView; run: Run; busy: boolean; onAt: Open; waiting: Waiting }) {
  const plan = view.plan!;
  const start = { chapter: plan.chapters[0].id, line: linesOf(plan.chapters[0])[0].id };
  // The line kept in the frame, and the one pointed at, which shows over it while it is.
  const [kept, setKept] = useState<Spot>(start);
  const [pointed, setPointed] = useState<Spot | null>(null);
  const spot = pointed ?? kept;
  const chapter = plan.chapters.find((c) => c.id === spot.chapter) ?? plan.chapters[0];
  const lines = linesOf(chapter);
  const line = lines.find((l) => l.id === spot.line) ?? lines[0];
  const number = plan.chapters.indexOf(chapter) + 1;
  const film = view.film_state;
  const rendered = film.status === "done" && film.file;
  // the size the film is rendered in: the one picked here, else the one asked for last
  const [picked, setPicked] = useState<FilmSize | null>(null);
  const size = picked ?? film.making ?? film.size ?? "hd";
  const hdTakes = view.takes.filter((t) => t.kept && t.video && !t.uhd).length;
  const next = plan.chapters.find((c) => !takeOf(view, c.id));
  // Something of the film is made or recorded: it can be rendered, and its chapters say where they stand.
  const started = view.status === "studio";
  // The next chapter's pictures that a take of it waits for.
  const count = next ? pictureCount(view, next.id) : null;
  const waits = count ? count.planned + count.making > 0 : false;
  const recorded = plan.chapters.filter((c) => takeOf(view, c.id)).length;
  // The length asked for is said only while the script is outside it: the checks decide that.
  const outside = Array.isArray(view.settings.seconds) && view.checks.some((c) => c.rule === "length") ? view.settings.seconds : null;
  const targets: AskTarget[] = [
    { scope: "film", label: "The whole film", name: "The film", hint: "Ask for a change to the film", presets: ["Make it shorter", "A stronger opening", "Plainer words"] },
  ];
  // Where the last change reached: its chapters are marked, so it is found without reading them all.
  const touched = useMemo(() => {
    const change = view.last_change;
    const changed = new Set([...(change?.lines ?? []), ...(change?.added ?? [])]);
    const cut = new Set((change?.cut ?? []).map((c) => c.chapter));
    return new Set(plan.chapters.filter((c) => cut.has(c.id) || linesOf(c).some((l) => changed.has(l.id))).map((c) => c.id));
  }, [view.last_change, plan.chapters]);
  const note = film.stale
    ? "Changed since it was rendered"
    : !film.status && started && recorded < plan.chapters.length
      ? "A draft shows a stand-in where you haven't recorded"
      : "";

  return (
      <section className="ep-doc" aria-label="The script">
        <div className="ep-doc-body">
          <div className="ep-doc-grid">
            <div className="ep-doc-main">
              <header className="ep-doc-head">
                <p className="ep-kicker">{started ? `${recorded} of ${plan.chapters.length} chapters recorded` : "Read it and change what you like, then make the pictures"}</p>
                <h1>{plan.brief.idea || view.title}</h1>
                <Byline view={view} />
                {view.checks.length > 0 && (
                  <details className="ep-more ep-flags">
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
              </header>
              {plan.chapters.map((c, i) => (
                <ChapterText
                  key={c.id}
                  view={view}
                  chapter={c}
                  number={i + 1}
                  kept={kept.line}
                  touched={touched.has(c.id)}
                  onPoint={(to) => setPointed(to)}
                  onKeep={(to) => setKept(to)}
                  onOpen={(line) => onAt(c.id, false, line)}
                />
              ))}
            </div>
            {/* the film, or the frame for the line pointed at, beside the script in the editor */}
            <aside className="ep-doc-aside" aria-label="The film">
              <div className="ep-float" style={{ top: 16 }}>
                {!rendered && <p className="ep-float-line">
                      Preview · chapter {number}, line {lines.indexOf(line) + 1} of {lines.length} · {LAYOUTS[line.layout] ?? line.layout}
                </p>}
                {rendered ? (
                  <video className="ep-film-video" src={film.file!.url} controls preload="metadata" />
                ) : (
                  <>
                    <Tooltip content={`Opens chapter ${number} at this line`} side="bottom">
                      <button
                        type="button"
                        className="ep-peek-stage ep-float-frame"
                        aria-label={`Open chapter ${number} at line ${lines.indexOf(line) + 1}`}
                        onClick={() => onAt(chapter.id, false, line.id)}
                      >
                        <FrameCanvas view={view} frame={line} unit={unitOf(view, line.id)} take={takeOf(view, chapter.id)} label={`The frame for chapter ${number}, line ${lines.indexOf(line) + 1}`} />
                        <span className="ep-peek-open" aria-hidden="true">
                          <ArrowRight />
                          Open
                        </span>
                      </button>
                    </Tooltip>
                  </>
                )}
                <div className="ep-film-sum">
                  <b>
                    {plan.chapters.length} chapters · {mmss(view.clock?.total ?? plan.totals.seconds)}
                    {rendered && film.size === "4k" ? " · 4K" : ""}
                    {outside && (
                      <span className="ep-film-asked">
                        {" "}
                        · asked for {mmss(outside[0])} to {mmss(outside[1])}
                      </span>
                    )}
                  </b>
                  {(film.blocked || note) && <span data-tone={film.status === "failed" ? "red" : film.stale ? "amber" : undefined}>{film.blocked || note}</span>}
                </div>
                {film.status && <RenderStatus film={film} />}
                {started && size === "4k" && film.status !== "rendering" && (
                  <p className="ep-notice">
                    4K takes about 2½ times as long to render as 1080p
                    {hdTakes > 0 ? `; ${hdTakes === 1 ? "one take is" : `${hdTakes} takes are`} HD and scaled up` : ""}.
                  </p>
                )}
                <div className="ep-peek-actions">
                  {next && (
                    <Tooltip content={waits ? "Its pictures are made first" : "Opens it with the camera on, ready for Space"} side="bottom">
                      <button type="button" className={`btn ${started ? "primary" : ""}`} onClick={() => onAt(next.id, true)}>
                        <Circle />
                        Record chapter {plan.chapters.indexOf(next) + 1}
                      </button>
                    </Tooltip>
                  )}
                  {started && (
                    // the render and the size it renders in, kept together as the row wraps
                    <span className="ep-render-pick">
                      <button
                        type="button"
                        className={`btn ${!next && (film.status !== "done" || film.stale) ? "primary" : ""}`}
                        disabled={busy || !!film.blocked || film.status === "rendering"}
                        onClick={() => void run(() => api.renderEpisode(view.id, size))}
                      >
                        <Clapperboard />
                        {film.status === "rendering" ? "Rendering" : film.status === "failed" ? "Retry render" : film.status === "done" ? "Render again" : next ? "Render a draft" : "Render the film"}
                      </button>
                      <SegmentedControl<FilmSize>
                        aria-label="The film's size"
                        value={size}
                        onChange={setPicked}
                        disabled={busy || film.status === "rendering"}
                        options={[
                          { value: "hd", label: "1080p" },
                          { value: "4k", label: "4K" },
                        ]}
                      />
                    </span>
                  )}
                </div>
              </div>
            </aside>
          </div>
        </div>
        <div className="ep-doc-grid ep-doc-foot">
          <div className="ep-doc-main">
            <Ask view={view} targets={targets} run={run} busy={busy} waiting={waiting} />
          </div>
          <span />
        </div>
      </section>
  );
}

// Who wrote the plan, under its title as a document's byline, opening onto each turn it took.
function Byline({ view }: { view: EpisodeView }) {
  return (
    <details className="ep-byline">
      <summary>
        <AgentMark mark={view.writer} size="sm" />
        <span>Written by {WRITERS[view.writer] ?? "an agent"}</span>
        <span className="faint">
          · {view.runs.length} {view.runs.length === 1 ? "turn" : "turns"}
        </span>
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
  );
}

// One chapter of the film's script: its question, then its lines as running text in its blocks.
function ChapterText({
  view,
  chapter,
  number,
  kept,
  touched,
  onPoint,
  onKeep,
  onOpen,
}: {
  view: EpisodeView;
  chapter: EpisodeChapter;
  number: number;
  kept: string;
  touched: boolean;
  onPoint: (spot: Spot | null) => void;
  onKeep: (spot: Spot) => void;
  onOpen: (line?: string) => void;
}) {
  const state = chapterState(view, chapter);
  const blocks = useMemo(() => blocksOf(view, linesOf(chapter)), [view, chapter]);
  const seconds = view.clock?.chapters.find((x) => x.id === chapter.id)?.seconds ?? chapter.seconds;
  const head = `nb-${chapter.id}`;
  return (
    <section className="ep-nb-chapter" aria-labelledby={head}>
      <header className="ep-nb-head">
        <b className="ep-num" data-state={state}>
          {number}
        </b>
        <h2 id={head}>
          <Tooltip content={`Opens chapter ${number}`} side="top" align="start">
            <button type="button" onClick={() => onOpen()}>
              {chapter.question}
            </button>
          </Tooltip>
        </h2>
        <small>
          {chapterMaking(view, chapter) && <WorkingMark said={state === "making"} />}
          {chapterName(chapter)} · {mmss(seconds)}
          {` · ${STATE_WORDS[state]}`}
        </small>
        {touched && <em className="ep-touched">Changed</em>}
      </header>
      {blocks.map((b) => (
        <div key={b.key} className="ep-nb-block" role="group" aria-label={blockName(b)}>
          <BlockHead block={b} view={view} />
          <p onMouseLeave={() => onPoint(null)}>
            {b.lines.flatMap((l) => {
              const spot = { chapter: chapter.id, line: l.id };
              // a span, not a button, so the lines run on as a paragraph and wrap mid-line
              return [
                <span
                  key={l.id}
                  role="button"
                  tabIndex={0}
                  className="ep-nb-line"
                  aria-current={kept === l.id || undefined}
                  aria-keyshortcuts="Enter"
                  onMouseEnter={() => onPoint(spot)}
                  onFocus={() => onKeep(spot)}
                  onClick={() => onKeep(spot)}
                  onDoubleClick={() => onOpen(l.id)}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter") return;
                    e.preventDefault();
                    onOpen(l.id);
                  }}
                >
                  {l.vo}
                </span>,
                " ",
              ];
            })}
          </p>
        </div>
      ))}
    </section>
  );
}
