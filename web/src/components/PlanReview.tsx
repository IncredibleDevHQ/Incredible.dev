// An episode's brief and its plan, reviewed in words. The brief is one page: the idea, who it is
// for, and the ledger of what the film may state, each claim with the material's own words. The
// plan is read as a deck. Its cover is the episode: the idea, and the whole film on one strip.
// Each chapter is one slide: its question as the title, its beats and frames laid out in time
// inside it, and what it ends on. The slides run down a filmstrip at the side, and what is
// picked on a slide (a beat, a frame, the chapter's row) is shown in full under it, the way a
// deck keeps its notes. Frames come after beats: a beat can stand without them while they are
// written, and a beat that changes marks its frames out of date. Pick any part and refine it on
// its own: the rest stays as it is, and the new version marks what it changed.
import { Check, ChevronRight, LayoutGrid, PanelRightClose, PanelRightOpen, Send, Sparkles, Undo2, X } from "lucide-react";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { api, type Board, type FrameView, type PlanBeat, type PlanRow, type PlanSection, type PlanShot } from "../api";
import { briefOf, chapterState, isChapter, isWritten, planOf, planWork, rowsOf, shotsOf, signOff, stageOf, STATE_WORDS, tone, topStage, type ChapterState } from "../plan";
import { useHouse } from "../store";
import { clock } from "../ui";
import { filmKeys, Thumb } from "./PlanFilm";
import { ChapterTimeline, EpisodeTimeline, step } from "./PlanTimeline";
import { TextArea } from "./TextArea";
import { ThinkingLoader } from "./ThinkingLoader";

// What the page shows: the brief, the episode, the spine, the script, the checks, or one chapter
// by its row.
type Page = string;
type Selection = { frame: string; row: string };
type Pending = { name: string; from: number; phases: string[] };

// A card on the canvas can open the plan at one chapter.
let openAt: Page | null = null;
export function openPlanAt(page: Page) {
  openAt = page;
}

const CHECK_WORDS = { pass: "Pass", fail: "Flag", wait: "Waiting" } as const;
// What each group of checks is about, as its card is headed.
const GROUP_WORDS: Record<string, string> = { time: "Time", structure: "Structure", words: "The voice" };
const BRIEF_WORDS: Record<string, string> = { approved: "Approved", changes: "Changes asked", review: "For review" };
// Whether the notes panel is open is the reader's own choice, kept on this computer. With none
// made yet it is open where the window has room for it beside a slide.
const NOTES_KEY = "creative-house:plan-notes";
const NOTES_ROOM = 1500;
function notesOpen(): boolean {
  try {
    const kept = window.localStorage.getItem(NOTES_KEY);
    if (kept) return kept === "open";
  } catch {
    // Storage can be blocked: the window's width decides.
  }
  return window.innerWidth >= NOTES_ROOM;
}

// Where a claim stands, as its row says it: looked up in the material, made up, or unsourced.
function standing(row: PlanRow): { words: string; chip: string } {
  if (row.status === "illustrative") return { words: "Illustrative", chip: "" };
  if (row.status === "unconfirmed") return { words: "Unconfirmed", chip: "amber" };
  if (row.found === false) return { words: "Not found in the material", chip: "amber" };
  return row.found ? { words: "In the material", chip: "green" } : { words: "Stated", chip: "" };
}

// A row of any section, by its id: a list's row, a beat or a frame.
function findRow(data: PlanSection | null | undefined, id: string): Record<string, unknown> | undefined {
  if (!data) return undefined;
  if (!isChapter(data)) return data.rows.find((r) => r.id === id) as Record<string, unknown> | undefined;
  for (const beat of data.beats) {
    if (beat.id === id) return beat as unknown as Record<string, unknown>;
    const shot = beat.shots?.find((s) => s.id === id);
    if (shot) return shot as unknown as Record<string, unknown>;
  }
  return undefined;
}

// Word by word, what a rewrite took out and put in.
function diff(before: string, after: string) {
  const a = before.split(" ");
  const b = after.split(" ");
  const keep = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--) keep[i][j] = a[i] === b[j] ? keep[i + 1][j + 1] + 1 : Math.max(keep[i + 1][j], keep[i][j + 1]);
  const out: { text: string; kind: "same" | "add" | "del" }[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) out.push({ text: a[i++], kind: (j++, "same") });
    else if (keep[i + 1][j] >= keep[i][j + 1]) out.push({ text: a[i++], kind: "del" });
    else out.push({ text: b[j++], kind: "add" });
  }
  while (i < a.length) out.push({ text: a[i++], kind: "del" });
  while (j < b.length) out.push({ text: b[j++], kind: "add" });
  return out;
}

// A section's text, with what its latest version changed marked in place until it is approved.
function textOf(frame: FrameView) {
  const changed = new Set(frame.data?.changed ?? []);
  const showing = frame.verdict !== "approved" && Boolean(frame.was);
  return (id: string, field: string, value: string | undefined): ReactNode => {
    if (!value) return value ?? "";
    if (!showing || !(changed.has(id) || changed.has("*"))) return value;
    const before = findRow(frame.was, id)?.[field];
    if (typeof before !== "string" || before === value) return value;
    return diff(before, value).map((part, n) => (
      <span key={n}>
        {n > 0 && " "}
        <span className={part.kind === "same" ? undefined : `pl-${part.kind}`}>{part.text}</span>
      </span>
    ));
  };
}

// What a selection is, as the side panel names it and the refine box asks about it. `layer` is
// what a section outside the chapters belongs to: the brief, or the plan's top layer.
function describe(frame: FrameView, row: string, layer: string) {
  const data = frame.data;
  if (isChapter(data)) {
    const head = `${frame.name} · ${data.title}`;
    const beat = data.beats.find((b) => b.id === row);
    if (beat) return { title: `${beat.id} · ${beat.title}`, kind: `A beat in ${frame.name}`, what: `beat ${beat.id}` };
    const owner = data.beats.find((b) => b.shots?.some((s) => s.id === row));
    if (owner) return { title: `Frame ${row}`, kind: `A frame in beat ${owner.id} of ${frame.name}`, what: `frame ${row}` };
    return { title: head, kind: "A chapter, with its beats and frames", what: frame.name };
  }
  const found = rowsOf(frame).find((r) => r.id === row);
  if (data?.section === "chapters") {
    return found
      ? { title: `${found.label} · ${found.title}`, kind: "Its question and result, from the chapter list", what: `${found.label}'s question and result` }
      : { title: "The chapter list", kind: "The top layer", what: "the chapter list" };
  }
  if (data?.section === "spine") {
    return found
      ? { title: found.label, kind: found.picked ? "The spine the episode follows" : "Another spine it could follow", what: `spine ${found.id}` }
      : { title: "Spine", kind: layer, what: "the spine" };
  }
  if (data?.section === "claims") {
    return found
      ? { title: `Claim ${found.id}`, kind: "A row of the ledger", what: `claim ${found.id}` }
      : { title: "What the film may state", kind: `The ledger · ${layer.toLowerCase()}`, what: "the ledger" };
  }
  return found
    ? { title: found.label, kind: `${frame.name} · ${layer.toLowerCase()}`, what: found.label.toLowerCase() }
    : { title: frame.name, kind: layer, what: frame.name.toLowerCase() };
}

export function PlanReview({ board, frame }: { board: Board; frame: FrameView }) {
  const openFrame = useHouse((s) => s.openFrame);
  const work = useHouse((s) => planWork(s, board.thread_id));
  const { lists, spine, table, listed, chapterOf, topSigned, allWritten } = planOf(board);
  const isBrief = board.kind === "brief";
  const layer = isBrief ? "The brief" : "The top layer";
  const checks = board.checks ?? [];
  const sign = signOff(board, work);
  // The idea is the brief's. A brief's own board holds it; a plan reads it from the brief it was
  // written from (a plan from before briefs had a board of their own carries it itself).
  const brief = lists.find((f) => rowsOf(f).some((r) => r.id === "idea"));
  const idea = rowsOf(brief).find((r) => r.id === "idea");
  const home = brief ?? table ?? spine ?? frame;
  const byPage = (p: Page) => chapterOf(listed.find((c) => c.id === p));

  const pageOf = (f: FrameView): Page =>
    isBrief ? "brief" : isChapter(f.data) ? (listed.find((c) => c.label === f.name)?.id ?? "episode") : f.data?.section === "spine" ? "spine" : "episode";
  const entry = (p: Page): Selection => {
    if (p === "spine" && spine) return { frame: spine.id, row: rowsOf(spine).find((r) => r.picked)?.id ?? "" };
    if (p === "checks") return { frame: home.id, row: "" };
    const chapter = byPage(p);
    if (chapter) return { frame: chapter.id, row: "" };
    if (table && listed.some((c) => c.id === p)) return { frame: table.id, row: p };
    return { frame: home.id, row: brief ? (idea?.id ?? "") : "" };
  };
  const [page, setPage] = useState<Page>(() => {
    const asked = openAt;
    openAt = null;
    return asked ?? pageOf(frame);
  });
  const [sel, setSel] = useState<Selection>(() => entry(page));
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  // The slide last looked at, to come back to from the script or the checks.
  const onDeck = (p: Page) => !["script", "checks", "brief"].includes(p);
  const [slide, setSlide] = useState<Page>(() => (onDeck(page) ? page : "episode"));
  const [notes, setNotes] = useState(notesOpen);
  const showNotes = (open: boolean) => {
    setNotes(open);
    try {
      window.localStorage.setItem(NOTES_KEY, open ? "open" : "closed");
    } catch {
      // Not kept: the choice still holds until the review is closed.
    }
  };

  const selected = board.frames.find((f) => f.id === sel.frame) ?? frame;
  const onChecks = page === "checks";
  const info = onChecks ? { title: "Checks", kind: "Worked out from the plan as it stands", what: "" } : describe(selected, sel.row, layer);
  const landed = Boolean(pending && (board.frames.find((f) => f.name === pending.name)?.version ?? 0) > pending.from);
  useEffect(() => {
    if (!landed) return;
    const done = window.setTimeout(() => setPending(null), 2600);
    return () => window.clearTimeout(done);
  }, [landed]);

  const pick = (frameId: string, row: string) => setSel({ frame: frameId, row });
  const go = (p: Page) => {
    setPage(p);
    if (onDeck(p)) setSlide(p);
    if (p !== "script") setSel(entry(p));
    document.querySelector(".pl-page")?.scrollTo({ top: 0 });
  };
  // A row of a chapter is on the page once its beat is the one picked, so look for it after that.
  const jump = (row: string, frameId = selected.id) => {
    pick(frameId, row);
    window.setTimeout(() => document.getElementById(`pl-${row}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
  };

  // ← and → walk a chapter's frames in order, as the film would play them.
  const open = isBrief ? undefined : chapterOf(listed.find((c) => c.id === page));
  useEffect(() => {
    const chapter = open?.data;
    if (!open || !isChapter(chapter)) return;
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof Element && e.target.closest("textarea, input");
      if ((e.key !== "ArrowRight" && e.key !== "ArrowLeft") || typing) return;
      e.preventDefault();
      setSel((now) => ({ frame: open.id, row: step(chapter, now.frame === open.id ? now.row : "", e.key === "ArrowRight" ? 1 : -1) }));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const fail = (error: unknown) => {
    setPending(null);
    useHouse.getState().say((error as Error).message);
  };
  const refine = async (text = draft) => {
    const words = text.trim();
    if (!words || !info.what) return;
    const phases = ["Reading your note", `Rewriting ${info.what}`, "Checking it"];
    setPending({ name: selected.name, from: selected.version, phases });
    try {
      await api.refinePlan(board.id, { frame_id: selected.id, text: words, row: sel.row });
      setDraft("");
    } catch (error) {
      fail(error);
    }
  };
  const addNote = async () => {
    const words = draft.trim();
    if (!words) return;
    await api.comment(selected.id, { text: words, anchor: sel.row });
    setDraft("");
  };
  const writeNow = async (name: string) => {
    setPending({ name, from: byPage(listed.find((c) => c.label === name)?.id ?? "")?.version ?? 0, phases: [`Writing ${name}`] });
    try {
      await api.writeChapter(board.id, name);
    } catch (error) {
      fail(error);
    }
  };

  const openNotes = (f: FrameView, row?: string) =>
    f.comments.filter((c) => !c.parent_id && !c.resolved && !c.answered_in && (row === undefined || c.anchor === row)).length;
  const unsent = board.frames.reduce((n, f) => n + openNotes(f), 0);
  const marks = (f: FrameView, id: string) => {
    const notes = openNotes(f, id);
    const revised = f.verdict !== "approved" && f.was && f.data?.changed?.some((c) => c === id || c === "*");
    if (!notes && !revised) return null;
    return (
      <span className="pl-marks">
        {revised && <span className="chip green">Revised in v{f.version}</span>}
        {notes > 0 && <span className="pl-count">{notes === 1 ? "1 note" : `${notes} notes`}</span>}
      </span>
    );
  };
  const isSel = (f: FrameView, row: string) => sel.frame === f.id && sel.row === row;
  // What is being written for a part right now. A chapter says which step it is on (its beats, or
  // its frames from them), as the pipeline reports it; anything else shows what was asked.
  const working = (name: string) => {
    const stage = stageOf(work, name);
    if (stage) return <ThinkingLoader size="sm" phases={[STATE_WORDS[stage]]} />;
    return pending?.name === name ? <ThinkingLoader size="sm" phases={pending.phases} interval={1800} done={landed} doneLabel="Done" /> : null;
  };
  const stateOf = (name: string): ChapterState => {
    const f = board.frames.find((x) => x.name === name && isChapter(x.data));
    const state = chapterState(f, topSigned, stageOf(work, name));
    return pending?.name === name && !f && state === "planned" ? "writing" : state;
  };

  // -- the filmstrip --------------------------------------------------------------------------
  const picked = rowsOf(spine).find((r) => r.picked);
  const writtenChapters = listed.filter((c) => isWritten(chapterOf(c))).length;
  const approvedChapters = listed.filter((c) => isWritten(chapterOf(c)) && chapterOf(c)?.verdict === "approved").length;
  const failing = checks.filter((c) => c.state === "fail").length;
  const notesOn = (c: PlanRow) => {
    const f = chapterOf(c);
    return (f ? openNotes(f) : 0) + (table ? openNotes(table, c.id) : 0);
  };
  const thumb = (c: PlanRow, large = false) => (
    <Thumb key={c.id} row={c} frame={chapterOf(c)} state={stateOf(c.label)} notes={notesOn(c)} current={!large && page === c.id} large={large} onOpen={() => go(c.id)} />
  );
  const film = (
    <nav className="pl-film" aria-label="The plan's slides" onKeyDown={filmKeys}>
      <div className="pl-film-head">
        <span>Chapters</span>
        <span className="mono">{listed.length}</span>
        <button type="button" className="icon-btn" aria-label="The whole episode" title="The whole episode" onClick={() => go("episode")}>
          <LayoutGrid />
        </button>
      </div>
      <div className="pl-progress">
        <span>{topStage(work) || (topSigned ? "Top layer approved" : "Top layer for review")}</span>
        <span>
          {writtenChapters < listed.length ? `${writtenChapters} of ${listed.length} chapters written` : `${approvedChapters} of ${listed.length} chapters approved`}
        </span>
        <span className="pl-bar">
          <span style={{ width: `${listed.length ? (approvedChapters / listed.length) * 100 : 0}%` }} />
        </span>
      </div>
      <button type="button" className="th th-cover" aria-current={page === "episode" || page === "spine" ? "page" : undefined} title="The episode" onClick={() => go("episode")}>
        <span className="th-top">
          <span className="pl-dot" data-state={topSigned ? "approved" : "review"} />
          <span className="th-label">The episode</span>
        </span>
        <b className="th-title">{idea?.text || board.brief?.idea || board.title}</b>
      </button>
      {listed.map((c) => thumb(c))}
    </nav>
  );

  // -- the pages -------------------------------------------------------------------------------
  const listCard = (f: FrameView, skip: string[] = []) => {
    const t = textOf(f);
    return (
      <section className="pl-card" key={f.id}>
        <button type="button" className="pl-card-head" aria-pressed={isSel(f, "")} onClick={() => pick(f.id, "")}>
          <b>{f.name}</b>
          {f.verdict === "approved" && <span className="chip green">Approved</span>}
          {working(f.name)}
        </button>
        {rowsOf(f)
          .filter((r) => !skip.includes(r.id))
          .map((r) => (
            <button type="button" key={r.id} id={`pl-${r.id}`} className="pl-row" aria-pressed={isSel(f, r.id)} onClick={() => pick(f.id, r.id)}>
              <span className="pl-k">{r.label}</span>
              <span>{t(r.id, "text", r.text)}</span>
              {marks(f, r.id)}
            </button>
          ))}
      </section>
    );
  };

  // The checks, one row each: what it found, and the rule it holds the work to. A plan has
  // enough of them to read in parts: one card for each thing they are about.
  const checkCards = () =>
    [...new Set(checks.map((c) => c.group ?? ""))].map((group, _, groups) => {
      const rows = checks.filter((c) => (c.group ?? "") === group);
      const flagged = rows.filter((c) => c.state === "fail").length;
      return (
        <section className="pl-card" key={group}>
          {groups.length > 1 && GROUP_WORDS[group] && (
            <div className="pl-card-head static">
              <b>{GROUP_WORDS[group]}</b>
              <span className="pl-soft">{flagged ? `${flagged} to look at` : rows.every((c) => c.state === "pass") ? "All pass" : ""}</span>
            </div>
          )}
          {rows.map((r) => (
            <div key={r.id} className="pl-row static">
              <span className="pl-k">
                <span className={`chip ${r.state === "pass" ? "green" : r.state === "fail" ? "amber" : ""}`}>{CHECK_WORDS[r.state]}</span>
              </span>
              <span>
                <b>{r.label}</b>
                <span className="pl-soft">{r.text}</span>
                <span className="pl-rule">{r.rule}</span>
              </span>
            </div>
          ))}
        </section>
      );
    });

  // The brief: the idea, the rows every later level leans on, and the ledger of what the film
  // may state, each claim beside the material's own words for it.
  const briefPage = () => {
    const { rows, ledger, stated, madeUp } = briefOf(board);
    const t = ledger ? textOf(ledger) : () => "";
    return (
      <>
        {rows && idea ? (
          <button type="button" className="pl-hero" id={`pl-${idea.id}`} aria-pressed={isSel(rows, idea.id)} onClick={() => pick(rows.id, idea.id)}>
            <span className="pl-kicker">The brief · the one idea</span>
            <span className="pl-title">{textOf(rows)(idea.id, "text", idea.text)}</span>
            {marks(rows, idea.id)}
          </button>
        ) : (
          <div className="pl-hero static">
            <span className="pl-kicker">The brief</span>
            <span className="pl-title">{board.title}</span>
          </div>
        )}
        {rows && listCard(rows, idea ? [idea.id] : [])}
        {ledger && (
          <section className="pl-card">
            <button type="button" className="pl-card-head" aria-pressed={isSel(ledger, "")} onClick={() => pick(ledger.id, "")}>
              <b>What the film may state</b>
              <span className="pl-soft">
                {stated} from the material{madeUp > 0 && `, ${madeUp} made up to show the idea`}
              </span>
              {working(ledger.name)}
            </button>
            {rowsOf(ledger).map((r) => {
              const { words, chip } = standing(r);
              return (
                <button type="button" key={r.id} id={`pl-${r.id}`} className="pl-row pl-claim" aria-pressed={isSel(ledger, r.id)} onClick={() => pick(ledger.id, r.id)}>
                  <span className="pl-k mono">{r.id}</span>
                  <span>
                    <span>{t(r.id, "claim", r.claim)}</span>
                    {r.quote && <span className="pl-quote">“{t(r.id, "quote", r.quote)}”</span>}
                  </span>
                  <span className="pl-marks">
                    <span className={`chip ${chip}`}>{words}</span>
                    {marks(ledger, r.id)}
                  </span>
                </button>
              );
            })}
          </section>
        )}
        {checkCards()}
      </>
    );
  };

  // One line of a slide's foot: what it is, then the words.
  const fact = (label: string, words: ReactNode) => (
    <span className="sl-fact" key={label}>
      <span className="pl-k">{label}</span>
      <span>{words}</span>
    </span>
  );

  // The cover: the idea as the deck's title, the whole film on one strip, and the lines that
  // frame it. Under it every chapter as a slide in small, then the top layer's own sections.
  const episodePage = () => {
    const t = table ? textOf(table) : () => "";
    const opens = listed[0];
    const closes = listed.at(-1);
    const turns = listed.find((c) => c.turn);
    const runs = closes?.time?.split("–")[1];
    // A framing line is its row's in the chapter list, so picking it picks that row.
    const framing = (c: PlanRow, label: string, words: ReactNode) =>
      table && (
        <button type="button" className="sl-fact" aria-pressed={isSel(table, c.id)} onClick={() => pick(table.id, c.id)}>
          <span className="pl-k">{label}</span>
          <span>{words}</span>
        </button>
      );
    return (
      <>
        <article className="sl sl-cover" aria-label="The episode">
          <div className="sl-head static">
            <span className="sl-kicker">
              <span>
                The episode{runs ? ` · ${runs}` : ""} · {listed.length} parts
              </span>
              {brief && idea && marks(brief, idea.id)}
              {spine && working(spine.name)}
            </span>
            {brief && idea ? (
              <button type="button" className="sl-title sl-pick" id={`pl-${idea.id}`} aria-pressed={isSel(brief, idea.id)} onClick={() => pick(brief.id, idea.id)}>
                {textOf(brief)(idea.id, "text", idea.text)}
              </button>
            ) : (
              <span className="sl-title">{board.brief?.idea || board.title}</span>
            )}
            {spine && picked && (
              <button type="button" className="sl-asks sl-pick" id={`pl-${picked.id}`} aria-pressed={isSel(spine, picked.id)} onClick={() => pick(spine.id, picked.id)}>
                {textOf(spine)(picked.id, "text", picked.text)}
                {marks(spine, picked.id)}
              </button>
            )}
            <span className="sl-links">
              {board.brief && (
                <button type="button" className="pl-more" onClick={() => openFrame(board.brief!.frame_id, board.brief!.board_id)}>
                  From the brief · {BRIEF_WORDS[board.brief.status] ?? "For review"} <ChevronRight size={14} />
                </button>
              )}
              {spine && (
                <button type="button" className="pl-more" onClick={() => go("spine")}>
                  The spine, picked from {rowsOf(spine).length} <ChevronRight size={14} />
                </button>
              )}
            </span>
          </div>
          <div className="sl-body">
            <EpisodeTimeline listed={listed} chapterOf={chapterOf} topSigned={topSigned} stageOf={(name) => stageOf(work, name)} onOpen={(c) => go(c.id)} />
          </div>
          <div className="sl-foot">
            {opens?.first &&
              framing(
                opens,
                "First line",
                <span className="pl-vo">
                  “{t(opens.id, "first", opens.first)}” <span className="pl-soft">· {opens.hook}</span>
                </span>,
              )}
            {turns && framing(turns, `The turn · ${turns.label}`, t(turns.id, "turn", turns.turn))}
            {closes?.last &&
              framing(
                closes,
                "Last line",
                <span className="pl-vo">
                  “{t(closes.id, "last", closes.last)}” {closes.landing && <span className="pl-soft">· {closes.landing}</span>}
                </span>,
              )}
          </div>
        </article>
        <section className="pl-grid" aria-label="Every chapter">
          {listed.map((c) => thumb(c, true))}
        </section>
        {brief && listCard(brief, idea ? [idea.id] : [])}
        {lists.filter((f) => f !== brief).map((f) => listCard(f))}
      </>
    );
  };

  const spinePage = () =>
    spine && (
      <>
        <div className="pl-hero static">
          <span className="pl-kicker">Spine</span>
          <span className="pl-title">One worked example the whole episode follows</span>
          <span className="pl-soft">Three candidates. The picked one runs through every chapter, so every beat has the same thing to point at.</span>
        </div>
        <div className="pl-spines">
          {rowsOf(spine).map((r) => (
            <button type="button" key={r.id} id={`pl-${r.id}`} className={`pl-spine ${r.picked ? "picked" : ""}`} aria-pressed={isSel(spine, r.id)} onClick={() => pick(spine.id, r.id)}>
              <span className="pl-spine-top">
                <b>{r.label}</b>
                {r.picked && <span className="chip green">Picked</span>}
              </span>
              <span className="pl-k">Follows</span>
              <span>{textOf(spine)(r.id, "text", r.text)}</span>
              <span className="pl-k">{r.picked ? "Shown as, and why" : "Shown as, and why not"}</span>
              <span className="pl-soft">{r.detail}</span>
              {marks(spine, r.id)}
            </button>
          ))}
        </div>
      </>
    );

  const frameCard = (f: FrameView, s: PlanShot) => {
    const t = textOf(f);
    const reads = s.on ? s.on.split(" / ") : [];
    return (
      <button type="button" key={s.id} id={`pl-${s.id}`} className="pl-frame" aria-pressed={isSel(f, s.id)} onClick={() => pick(f.id, s.id)}>
        <span className="pl-sketch">
          <span className="pl-move">{t(s.id, "move", s.move)}</span>
          <span className="pl-when">{s.time}</span>
          {reads.length ? (
            <span className="pl-words">
              {reads.map((r, n) => (
                <span key={n}>{r}</span>
              ))}
            </span>
          ) : (
            <span className="pl-scene">{t(s.id, "shows", s.shows)}</span>
          )}
        </span>
        <span className="pl-frame-head">
          <b>Frame {s.id}</b>
          <span className="mono">{s.seconds} s</span>
          {marks(f, s.id)}
        </span>
        {reads.length > 0 && (
          <span className="pl-line">
            <span className="pl-k">Shows</span>
            <span>{t(s.id, "shows", s.shows)}</span>
          </span>
        )}
        {s.vo && (
          <span className="pl-line">
            <span className="pl-k">Voice</span>
            <span className="pl-vo">“{t(s.id, "vo", s.vo)}”</span>
          </span>
        )}
        {s.sound && (
          <span className="pl-line">
            <span className="pl-k">Sound</span>
            <span className="pl-soft">{t(s.id, "sound", s.sound)}</span>
          </span>
        )}
      </button>
    );
  };

  // A beat in full, under its slide: its point, the frames written from it, then what the beat
  // asks of the picture. Without frames yet, it says they come next; with frames written from
  // an earlier version of it, it says they are out of date.
  const beatBlock = (f: FrameView, b: PlanBeat) => {
    const t = textOf(f);
    const shots = b.shots ?? [];
    const stage = stageOf(work, f.name);
    return (
      <section className="pl-beat" key={b.id}>
        <button type="button" id={`pl-${b.id}`} className="pl-beat-head" aria-pressed={isSel(f, b.id)} onClick={() => pick(f.id, b.id)}>
          <span className="pl-beat-top">
            <span className="pl-id">{b.id}</span>
            <b>{b.title}</b>
            <span className="mono">{b.time}</span>
            {b.technique && <span className="chip">{b.technique}</span>}
            {marks(f, b.id)}
          </span>
          <span className="pl-take">{t(b.id, "takeaway", b.takeaway)}</span>
        </button>
        {b.stale && (
          <p className="pl-stale">
            <b>Out of date.</b> These frames were written from this beat as it was. {stage === "frames" ? "They are being written again from it now." : "They are written again from it before the plan is approved."}
          </p>
        )}
        {shots.length > 0 ? (
          <div className={`pl-frames ${b.stale ? "stale" : ""}`}>{shots.map((s) => frameCard(f, s))}</div>
        ) : (
          <div className="pl-frames-wait">
            {stage === "frames" ? <ThinkingLoader size="sm" phases={["Writing its frames from this beat"]} /> : <span>Its frames are written from this beat next.</span>}
          </div>
        )}
        <div className="pl-facts">
          {b.says !== undefined && (shots.length === 0 || b.stale) && (
            <>
              <span className="pl-k">Voice</span>
              {b.says ? <span className="pl-vo">“{t(b.id, "says", b.says)}”</span> : <span className="pl-soft">Plays in silence.</span>}
            </>
          )}
          <span className="pl-k">The change</span>
          <span>{t(b.id, "change", b.change)}</span>
          <span className="pl-k">Ends with</span>
          <span>{t(b.id, "result", b.result)}</span>
          <span className="pl-k">Watch</span>
          <span>
            {t(b.id, "focal", b.focal)}
            {b.demands?.length > 0 && <span className="pl-soft"> · to work out: {b.demands.join("; ")}</span>}
          </span>
          <span className="pl-k">Carries</span>
          <span className="pl-soft">
            {b.enters} → {b.leaves}
          </span>
          {b.claim && (
            <>
              <span className="pl-k">Claim</span>
              <span className="pl-soft">{b.claim}</span>
            </>
          )}
        </div>
      </section>
    );
  };

  // What a chapter's row says beyond its slide: the shape of its argument, its share of the
  // material, its sound and what crosses the cut into it. Its writers are held to these.
  const contract = (row: PlanRow) => {
    if (!table) return null;
    const t = textOf(table);
    const lines: [string, ReactNode][] = [
      ["Shape", row.shape],
      ["Covers", t(row.id, "covers", row.covers)],
      ["Sound", row.cue],
      ["Handoff in", row.handoff],
    ];
    const said = lines.filter(([, words]) => words);
    if (!said.length) return null;
    return (
      <section className="pl-card pl-contract">
        <div className="pl-contract-top">
          <b>From the chapter list</b>
          <span className="pl-soft">What its writers are held to</span>
        </div>
        <div className="pl-qa">
          {said.map(([label, words]) => (
            <Fragment key={label}>
              <span className="pl-k">{label}</span>
              <span>{words}</span>
            </Fragment>
          ))}
        </div>
      </section>
    );
  };

  // A chapter as one slide: its question under its title, its beats and frames in time inside
  // it, and what it ends on. Under the slide, whatever is picked on it is shown in full: a beat
  // with its frames, or the rest of the chapter's row.
  const chapterPage = (key: Page) => {
    const row = listed.find((c) => c.id === key);
    if (!row) return null;
    const f = chapterOf(row);
    const data = f && isChapter(f.data) ? f.data : null;
    const state = stateOf(row.label);
    const frames = data ? shotsOf(data) : [];
    const t = table ? textOf(table) : () => "";
    const onRow = Boolean(table && isSel(table, row.id));
    const pickRow = () => table && pick(table.id, row.id);
    // The beat shown in full under the slide: the one picked, or the one a picked frame is in.
    const at = f && sel.frame === f.id ? sel.row : "";
    const current = data?.beats.find((b) => b.id === at || b.shots?.some((s) => s.id === at)) ?? data?.beats[0];
    const counts = data ? [`${data.beats.length} beats`, frames.length ? `${frames.length} frames` : "", data.words ?? ""].filter(Boolean).join(" · ") : "";
    return (
      <>
        <article className="sl" aria-label={`${row.label}: ${row.title}`}>
          <button type="button" id={`pl-${row.id}`} className="sl-head" aria-pressed={onRow} onClick={pickRow}>
            <span className="sl-kicker">
              <span>
                {row.label} · {row.time} · {row.seconds} s
              </span>
              {table && marks(table, row.id)}
              <span className="pl-state" data-state={tone(state)}>
                {STATE_WORDS[state]}
              </span>
            </span>
            <span className="sl-title">{row.title}</span>
            <span className="sl-asks">{t(row.id, "asks", row.asks)}</span>
          </button>
          <div className="sl-body">
            {f && data ? (
              <ChapterTimeline
                chapter={data}
                selected={sel.frame === f.id ? sel.row : ""}
                noted={(id) => openNotes(f, id)}
                onPick={(id) => pick(f.id, id)}
                meta={<span className="tl-meta">{counts}</span>}
              />
            ) : (
              <div className="sl-wait">
                {state !== "planned" ? (working(row.label) ?? <ThinkingLoader size="sm" phases={[STATE_WORDS[state]]} />) : <span>Its beats and frames are written once the top layer is signed off.</span>}
              </div>
            )}
          </div>
          <button type="button" className="sl-foot" onClick={pickRow}>
            {fact("Ends with", t(row.id, "ends", row.ends))}
            {row.first &&
              fact(
                "First line",
                <span className="pl-vo">
                  “{t(row.id, "first", row.first)}” <span className="pl-soft">· {row.hook}</span>
                </span>,
              )}
            {row.turn && fact("The turn", t(row.id, "turn", row.turn))}
            {row.last &&
              fact(
                "Last line",
                <span className="pl-vo">
                  “{t(row.id, "last", row.last)}” {row.landing && <span className="pl-soft">· {row.landing}</span>}
                </span>,
              )}
          </button>
        </article>
        {f && data ? (
          <>
            {working(f.name)}
            {(state === "half" || state === "stale") && !pending && (
              <div className="pl-empty">
                <p>
                  <b>{state === "stale" ? "A beat changed after its frames were written." : "This chapter has its beats, and no frames yet."}</b> Frames are written from
                  the beats, so they are written {state === "stale" ? "again " : ""}next.
                </p>
                <button type="button" className="btn primary" onClick={() => void writeNow(row.label)}>
                  <Sparkles />
                  {state === "stale" ? "Write its frames again" : "Write its frames"}
                </button>
              </div>
            )}
            {onRow ? contract(row) : current && beatBlock(f, current)}
          </>
        ) : (
          <>
            {contract(row)}
            {state === "planned" && (
              <div className="pl-empty">
                <p>
                  <b>Its beats and frames aren't written yet.</b> Every chapter is written once the top layer is signed off: its beats first, then
                  its frames, from those beats. You can have this one written now, on its own.
                </p>
                <button type="button" className="btn primary" disabled={Boolean(pending)} onClick={() => void writeNow(row.label)}>
                  <Sparkles />
                  Write this chapter now
                </button>
              </div>
            )}
          </>
        )}
      </>
    );
  };

  const scriptPage = () => (
    <>
      <div className="pl-hero static">
        <span className="pl-kicker">Script</span>
        <span className="pl-title">The narration, read straight through</span>
        <span className="pl-soft">Each passage is a beat's voice, so a note here is a note on that beat.</span>
      </div>
      {listed.map((c) => {
        const f = chapterOf(c);
        if (!f || !isChapter(f.data)) {
          return (
            <section className="pl-card" key={c.id}>
              <div className="pl-card-head static">
                <b>
                  {c.label} · {c.title}
                </b>
                <span className="pl-soft">Not written yet</span>
              </div>
            </section>
          );
        }
        const t = textOf(f);
        // A chapter from before the voice was the beat's: its frames' lines, in order.
        const lines = f.data.beats.some((b) => b.says !== undefined)
          ? f.data.beats.filter((b) => b.says).map((b) => ({ id: b.id, field: "says", text: b.says }))
          : shotsOf(f.data)
              .filter((x) => x.vo)
              .map((x) => ({ id: x.id, field: "vo", text: x.vo }));
        return (
          <section className="pl-card" key={c.id}>
            <button type="button" className="pl-card-head" aria-pressed={isSel(f, "")} onClick={() => pick(f.id, "")}>
              <b>
                {c.label} · {c.title}
              </b>
              <span className="mono pl-soft">{f.data.words}</span>
            </button>
            {lines.map((line) => (
              <button type="button" key={line.id} className="pl-row pl-script" aria-pressed={isSel(f, line.id)} onClick={() => pick(f.id, line.id)}>
                <span className="mono pl-soft">{line.id}</span>
                <span className="pl-vo">{t(line.id, line.field, line.text)}</span>
                {marks(f, line.id)}
              </button>
            ))}
          </section>
        );
      })}
    </>
  );

  const checksPage = () => (
    <>
      <div className="pl-hero static">
        <span className="pl-kicker">Checks</span>
        <span className="pl-title">Worked out from the plan as it stands</span>
        <span className="pl-soft">The clock, the shape of the chapter list and how the voice reads are worked out from the plan, not written. They run again whenever a section changes.</span>
      </div>
      {checkCards()}
    </>
  );

  const pageTitle =
    page === "episode" || page === "brief" ? "" : page === "spine" ? "Spine" : page === "script" ? "Script" : page === "checks" ? "Checks" : (() => {
      const c = listed.find((x) => x.id === page);
      return c ? `${c.label} · ${c.title}` : page;
    })();
  const rowCrumb = selected.data && isChapter(selected.data) && sel.row && page !== "script" ? info.title : "";

  // -- the side panel --------------------------------------------------------------------------
  const roots = selected.comments.filter((c) => !c.parent_id);
  const label = (row: string) => (row ? describe(selected, row, layer).title : "");
  const approveLabel = isChapter(selected.data) ? "Approve chapter" : selected.data?.section === "chapters" ? "Approve the list" : "Approve section";
  const canRefine = Boolean(info.what) && !onChecks;

  const deck = !isBrief && onDeck(page);
  return (
    <div className="review plan-review" data-notes={notes ? undefined : "closed"} role="dialog" aria-modal="true" aria-label={`Review ${board.title}`}>
      <div className="pl-stage">
        <div className="pl-top">
          <button type="button" className="icon-btn" aria-label="Close" onClick={() => openFrame(null)}>
            <X />
          </button>
          <nav className="pl-crumbs" aria-label="Where you are in the plan">
            <button type="button" onClick={() => go(isBrief ? "brief" : "episode")}>
              {board.title}
            </button>
            {pageTitle && (
              <>
                <ChevronRight size={14} aria-hidden="true" />
                <button type="button" onClick={() => go(page)}>
                  {pageTitle}
                </button>
              </>
            )}
            {rowCrumb && (
              <>
                <ChevronRight size={14} aria-hidden="true" />
                <span>{rowCrumb}</span>
              </>
            )}
          </nav>
          {!isBrief && (
            <span className="seg" role="group" aria-label="How to read the plan">
              <button type="button" aria-pressed={deck} onClick={() => go(slide)}>
                Chapters
              </button>
              <button type="button" aria-pressed={page === "script"} onClick={() => go("script")}>
                Script
              </button>
              {checks.length > 0 && (
                <button type="button" aria-pressed={page === "checks"} onClick={() => go("checks")}>
                  Checks
                  {failing > 0 && <span className="pl-count">{failing}</span>}
                </button>
              )}
            </span>
          )}
          <span className="mono faint">v{board.version}</span>
          {board.status !== "approved" && (
            <>
              {unsent > 0 && (
                <button type="button" className="btn" onClick={() => void api.sendBoard(board.id, false)}>
                  <Send />
                  Send {unsent} {unsent === 1 ? "note" : "notes"}
                </button>
              )}
              <button
                type="button"
                className="btn primary"
                disabled={sign.busy}
                title={failing ? `${failing} ${failing === 1 ? "check fails" : "checks fail"}: see Checks` : undefined}
                onClick={() => void api.sendBoard(board.id, true).then(() => (isBrief || allWritten) && openFrame(null))}
              >
                <Check />
                {sign.label}
              </button>
            </>
          )}
          <button type="button" className="icon-btn" aria-pressed={notes} aria-label={notes ? "Hide the notes" : "Show the notes"} title={notes ? "Hide the notes" : "Notes, and refining a part"} onClick={() => showNotes(!notes)}>
            {notes ? <PanelRightClose /> : <PanelRightOpen />}
          </button>
        </div>
        <div className={`pl-body ${isBrief ? "single" : ""}`}>
          {!isBrief && film}
          <main className="pl-page" data-view={deck ? "deck" : "read"}>
            {isBrief ? briefPage() : page === "episode" ? episodePage() : page === "spine" ? spinePage() : page === "script" ? scriptPage() : page === "checks" ? checksPage() : chapterPage(page)}
          </main>
        </div>
      </div>
      <aside className="review-side pl-side" data-theme="dark">
        <header>
          <div>
            <b>{info.title}</b>
            <p className="muted" style={{ margin: "2px 0 0", fontSize: 13 }}>
              {info.kind}
            </p>
          </div>
          {!onChecks && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" className={`btn ${selected.verdict === "approved" ? "primary" : ""}`} onClick={() => void api.verdict(selected.id, selected.verdict === "approved" ? "" : "approved")}>
                <Check />
                {selected.verdict === "approved" ? "Approved" : approveLabel}
              </button>
              <button type="button" className={`btn ${selected.verdict === "changes" ? "warn" : ""}`} onClick={() => void api.verdict(selected.id, selected.verdict === "changes" ? "" : "changes")}>
                <Undo2 />
                {selected.verdict === "changes" ? "Changes asked" : "Ask for changes"}
              </button>
            </div>
          )}
          {pending?.name === selected.name && <div className="pl-working">{working(selected.name)}</div>}
        </header>
        <div className="notes" aria-label="Notes">
          {!onChecks && roots.length === 0 && <p className="muted" style={{ padding: "8px 16px", margin: 0 }}>No notes on {selected.name === info.title ? "this section" : info.what || "this"} yet.</p>}
          {(onChecks ? [] : roots).map((c, i) => (
            <div key={c.id} className={`note ${sel.row && c.anchor === sel.row ? "hot" : ""} ${c.resolved ? "resolved" : ""} ${c.answered_in ? "answered" : ""}`}>
              <span className="n">{i + 1}</span>
              <div>
                <div className="msg-head">
                  <strong>{c.author}</strong>
                  <time>{clock(c.created_at)}</time>
                </div>
                <p>{c.text}</p>
              </div>
              <div className="row">
                {c.anchor && (
                  <button type="button" className="linkish" onClick={() => jump(c.anchor)}>
                    {label(c.anchor)}
                  </button>
                )}
                <span className="mono">on v{c.version}</span>
                {c.answered_in ? <span className="chip green">Answered in v{c.answered_in}</span> : null}
                <button type="button" className="linkish" onClick={() => void api.resolve(c.id, !c.resolved)}>
                  {c.resolved ? "Reopen" : "Resolve"}
                </button>
              </div>
            </div>
          ))}
        </div>
        <div className="new-note pl-compose">
          {canRefine ? (
            <>
              <TextArea
                label={`Refine ${info.what} only`}
                minRows={2}
                maxRows={8}
                value={draft}
                placeholder="What should change?"
                hint={`⌘↵ refines it now. The rest of the ${isBrief ? "brief" : "plan"} stays as it is.`}
                onChange={(e) => setDraft(e.target.value)}
                onSubmitShortcut={(value) => void refine(value)}
              />
              <div className="pl-compose-actions">
                <button type="button" className="btn" disabled={!draft.trim()} onClick={() => void addNote()}>
                  Add note
                </button>
                <button type="button" className="btn refine" disabled={!draft.trim() || Boolean(pending)} onClick={() => void refine()}>
                  <Sparkles />
                  Refine now
                </button>
              </div>
            </>
          ) : (
            <p>{onChecks ? "Checks are worked out from the plan, so they change when a section does. To fix one, refine the frame or beat it names." : "Pick a part of the plan to refine it."}</p>
          )}
        </div>
      </aside>
    </div>
  );
}
