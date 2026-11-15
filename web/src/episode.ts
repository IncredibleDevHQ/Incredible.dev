// What the studio reads off an episode: its lines, each line's picture and take, and where a
// chapter stands. The server derives every number (episode_desk.py); nothing here recounts one.
import type { EpisodeChapter, EpisodeFrame, EpisodeLine, EpisodeTake, EpisodeUnit, EpisodeView, LayoutSpot, Presence } from "./api";

export const PRESENCE: Record<Presence, string> = { person: "You", both: "Both", content: "Picture" };
export const LAYOUTS: Record<string, string> = {
  "full-frame": "Full frame",
  "full-frame-close": "Close",
  "framed-on-ground": "Framed",
  "glass-card": "Glass card",
  split: "Split",
  "panel-and-portrait": "Panel and portrait",
  "corner-window": "Corner window",
  "avatar-bubble": "Small portrait",
  "graphic-on-ground": "Full screen",
  "card-on-ground": "Card",
  "recording-fills": "Recording",
  "title-card": "Title",
};
// A film's look, by a name short enough for a chip.
export const LOOKS: Record<string, string> = {
  "corner-window": "Corner window",
  "panel-and-portrait": "Panel and portrait",
  "framed-stage": "Framed stage",
  "expert-to-camera": "To camera",
  "voice-only": "Voice only",
};
export const CHAPTERS: Record<string, string> = {
  introduction: "Introduction",
  "demo-first": "Demo first",
  problem: "Problem",
  story: "Story",
  concept: "Concept",
  "how-it-works": "How it works",
  "options-compared": "Options compared",
  "worked-example": "Worked example",
  demo: "Demo",
  build: "Build",
  "feature-tour": "Feature tour",
  advice: "Advice",
  questions: "Questions",
  series: "Series",
  recap: "Recap",
  outro: "Outro",
};
export const PICTURES: Record<string, string> = {
  diagram: "Diagram",
  list: "List",
  chips: "Chips",
  "typeset-code": "Code",
  illustration: "Illustration",
  slide: "Slide",
  "number-card": "Number",
  "title-card": "Title",
  terminal: "Terminal",
  "product-screen": "Product screen",
  document: "Document",
  "product-output": "Output",
};

export const TRANSITIONS: Record<string, string> = { none: "Hold", cut: "Cut", push: "Push", crossfade: "Crossfade", "zoom-through": "Zoom in" };

// Whole seconds first, so 59.6 reads 1:00 and never 0:60.
export const mmss = (seconds: number) => {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
};
export const linesOf = (chapter: EpisodeChapter): EpisodeFrame[] => chapter.beats.flatMap((b) => b.frames);
export const chapterName = (chapter: EpisodeChapter) => CHAPTERS[chapter.type ?? ""] ?? "Chapter";
export const unitOf = (view: EpisodeView, frame: string): EpisodeUnit | undefined => view.units.find((u) => u.frames.includes(frame));
export const allLines = (view: EpisodeView): { chapter: string; line: EpisodeFrame }[] =>
  (view.plan?.chapters ?? []).flatMap((c) => linesOf(c).map((line) => ({ chapter: c.id, line })));
// The lines a layout set for a chapter (or the whole film) reaches: the ones of that presence.
export const linesIn = (view: EpisodeView, presence: Presence, chapter?: string) =>
  allLines(view).filter((x) => x.line.presence === presence && (!chapter || x.chapter === chapter));
// The pictures a layout set that widely would redraw: each is drawn for its first line's box.
export function redrawnBy(view: EpisodeView, presence: Presence, layout: string, chapter?: string): number {
  const reached = new Map(linesIn(view, presence, chapter).map((x) => [x.line.id, x.line]));
  return view.units.filter((u) => {
    const first = reached.get(u.frames[0]);
    return first && first.layout !== layout && !(first.override && !first.override.scope);
  }).length;
}
export const takeOf = (view: EpisodeView, chapter: string): EpisodeTake | undefined => view.takes.find((t) => t.kept && t.chapter === chapter && !t.frame);
export const clockLine = (view: EpisodeView, frame: string): EpisodeLine | undefined => view.clock?.lines.find((l) => l.frame === frame);
export const spotOf = (view: EpisodeView, layout: string): LayoutSpot =>
  view.options.geometry.layouts[layout] ?? view.options.geometry.layouts["graphic-on-ground"];

// Where a chapter stands, as its dot in the bar is coloured and its row reads.
export type ChapterState = "making" | "go" | "failed" | "ready" | "recorded";
export function chapterState(view: EpisodeView, chapter: EpisodeChapter): ChapterState {
  const units = view.units.filter((u) => u.chapter === chapter.id);
  if (takeOf(view, chapter.id)) return "recorded";
  if (units.some((u) => u.picture.status === "go")) return "go";
  if (units.some((u) => u.kind === "undesigned" || ["queued", "making", "posing", "none"].includes(u.picture.status))) return "making";
  if (units.some((u) => u.picture.status === "failed")) return "failed";
  return "ready";
}
export const STATE_WORDS: Record<ChapterState, string> = {
  making: "Pictures being made",
  go: "Stills need your go",
  failed: "A picture failed",
  ready: "Ready to record",
  recorded: "Recorded",
};

// Where the film's pictures stand: made, on their way, or stopped until someone asks again.
export function pictureCount(view: EpisodeView) {
  const all = view.units.filter((u) => u.kind === "picture");
  return {
    all: all.length,
    made: all.filter((u) => u.picture.status === "go" || (u.picture.status === "made" && !u.picture.stale)).length,
    making: all.filter((u) => ["queued", "making", "posing"].includes(u.picture.status)).length,
    stopped: all.filter((u) => u.picture.status === "failed").length,
  };
}

// What a picture's state reads as beside its line.
export function pictureWords(unit: EpisodeUnit, approved = true): string {
  if (unit.kind === "undesigned") return "Being planned";
  if (!approved) return "Planned";
  const p = unit.picture;
  if (p.status === "failed") return "Failed";
  if (p.status === "go") return "Needs your go";
  if (p.status === "made") return p.stale ? "Being remade" : "Made";
  if (p.status === "posing") return "Posing stills";
  return "Being made";
}

// A box of the 1920 by 1080 frame as CSS on a stage of any size.
export function boxStyle(box: [number, number, number, number], frame: [number, number], radius = 0): React.CSSProperties {
  const [x, y, w, h] = box;
  return {
    left: `${(x / frame[0]) * 100}%`,
    top: `${(y / frame[1]) * 100}%`,
    width: `${(w / frame[0]) * 100}%`,
    height: `${(h / frame[1]) * 100}%`,
    borderRadius: `calc(${Math.min(radius, 400) / frame[0]} * 100cqw)`,
  };
}
