// What a plan's board says about itself: its sections, the chapters its list names, which of them
// are written (beats, and frames written from each beat as it stands), and where each stands.
import type { Board, FrameView, PlanRow, PlanSection, PlanShot, Work } from "./api";

export type Chapter = Extract<PlanSection, { section: "chapter" }>;
// What is being written for a chapter right now: its beats, or its frames from those beats.
export type Stage = "beats" | "frames" | null;
export type ChapterState = "planned" | "writing" | "beats" | "frames" | "half" | "stale" | "review" | "changes" | "approved";

export const isChapter = (data: PlanSection | null | undefined): data is Chapter => data?.section === "chapter";
export const rowsOf = (frame: FrameView | undefined): PlanRow[] => (frame?.data && !isChapter(frame.data) ? frame.data.rows : []);
export const shotsOf = (data: Chapter): PlanShot[] => data.beats.flatMap((b) => b.shots ?? []);
// A chapter is written when every beat has frames written from it as it stands.
export const isWritten = (frame: FrameView | undefined) =>
  isChapter(frame?.data) && frame.data.beats.length > 0 && frame.data.beats.every((b) => (b.shots?.length ?? 0) > 0 && !b.stale);

export function planOf(board: Board) {
  const sections = board.frames.filter((f) => f.data);
  const table = sections.find((f) => f.data?.section === "chapters");
  const byName = new Map(sections.filter((f) => isChapter(f.data)).map((f) => [f.name, f] as const));
  const listed = rowsOf(table);
  const chapterOf = (row: PlanRow | undefined) => (row ? byName.get(row.label) : undefined);
  return {
    sections,
    lists: sections.filter((f) => f.data?.section === "list"),
    spine: sections.find((f) => f.data?.section === "spine"),
    table,
    listed,
    chapterOf,
    topSigned: sections.filter((f) => f.data?.layer === "top").every((f) => f.verdict === "approved"),
    allWritten: listed.length > 0 && listed.every((c) => isWritten(chapterOf(c))),
  };
}

// The step a running plan pipeline is on for one chapter, from the job's steps as it names them
// ("Chapter 2: beats", "Chapter 2: shots", "Chapter 2: beats as they stand", and the same with
// ", fix" when a step went back).
export function stageOf(work: Work[], name: string): Stage {
  for (const job of work) {
    if (job.kind !== "pipeline" || job.status !== "running") continue;
    const running = [...job.steps].reverse().find((s) => s.status === "running" && s.title.startsWith(`${name}: `));
    const step = running?.title.slice(name.length + 2) ?? "";
    // Reading the beats back as they stand is the start of writing the frames from them.
    if (running) return step.startsWith("shots") || step.includes("as they stand") ? "frames" : "beats";
  }
  return null;
}

// The step a running plan pipeline is on when it is not a chapter's, in words, or nothing: the
// brief, the top layer's two steps, or the first reader going through the chapters.
export function topStage(work: Work[]): string {
  const steps = work.filter((w) => w.kind === "pipeline" && w.status === "running").flatMap((w) => w.steps);
  const running = [...steps].reverse().find((s) => s.status === "running");
  if (running?.title.startsWith("brief")) return "Writing the brief from the material";
  if (running?.title.startsWith("spine")) return "Picking the spine";
  if (running?.title.startsWith("chapter list")) return "Writing the chapter list from the spine";
  if (running?.title.startsWith("reader")) return "A first reader is going through the script";
  return "";
}

// A brief's two sections: its rows, and the ledger of what the film may state.
export function briefOf(board: Board) {
  const sections = board.frames.filter((f) => f.data);
  const rows = sections.find((f) => f.data?.section === "list");
  const ledger = sections.find((f) => f.data?.section === "claims");
  const claims = rowsOf(ledger);
  return {
    rows,
    ledger,
    idea: rowsOf(rows).find((r) => r.id === "idea"),
    stated: claims.filter((c) => c.status === "stated").length,
    madeUp: claims.filter((c) => c.status === "illustrative").length,
    missing: claims.filter((c) => c.status === "unconfirmed" || c.found === false).length,
  };
}

// Where a chapter the plan lists stands.
export function chapterState(frame: FrameView | undefined, topSigned: boolean, stage: Stage = null): ChapterState {
  if (stage) return stage;
  if (!frame) return topSigned ? "writing" : "planned";
  if (isChapter(frame.data) && !isWritten(frame)) return frame.data.beats.some((b) => b.stale) ? "stale" : "half";
  return frame.verdict === "approved" ? "approved" : frame.verdict === "changes" ? "changes" : "review";
}

export const STATE_WORDS: Record<ChapterState, string> = {
  planned: "Not written yet",
  writing: "Being written",
  beats: "Writing its beats",
  frames: "Writing its frames from the beats",
  half: "Beats written, frames to come",
  stale: "A beat changed: its frames are out of date",
  review: "For review",
  changes: "Changes asked",
  approved: "Approved",
};
// How a state is drawn: the five the styles know.
export const tone = (state: ChapterState) =>
  state === "beats" || state === "frames" || state === "half" ? "writing" : state === "stale" ? "changes" : state;

const NO_WORK: Work[] = [];
type Held = { details: Record<string, { work: Work[] } | undefined>; canvas: Record<string, { thread: { id: string }; work: Work[] }[]> };
// A task's background work, from wherever the app holds it: its open thread, or its canvas.
export function planWork(state: Held, threadId: string): Work[] {
  const open = state.details[threadId]?.work;
  if (open) return open;
  for (const tasks of Object.values(state.canvas)) {
    const task = tasks.find((t) => t.thread.id === threadId);
    if (task) return task.work;
  }
  return NO_WORK;
}

// What the plan's sign-off button does now: sign the top layer off, have the chapters still
// missing written (its top layer is signed off, and a chapter has no frames or has stale ones),
// or sign the whole plan off. While its chapters are being written there is nothing to press.
export function signOff(board: Board, work: Work[]) {
  if (board.kind === "brief") return { label: "Approve brief", busy: false };
  const { topSigned, allWritten } = planOf(board);
  const writing = work.some((w) => w.kind === "pipeline" && w.status === "running");
  if (allWritten) return { label: "Approve plan", busy: false };
  if (!topSigned) return { label: "Approve top layer", busy: false };
  return writing ? { label: "Chapters are being written", busy: true } : { label: "Write what is left", busy: false };
}
