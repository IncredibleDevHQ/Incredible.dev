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

export const mmss = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
export const linesOf = (chapter: EpisodeChapter): EpisodeFrame[] => chapter.beats.flatMap((b) => b.frames);
export const chapterName = (chapter: EpisodeChapter) => CHAPTERS[chapter.type ?? ""] ?? "Chapter";
export const unitOf = (view: EpisodeView, frame: string): EpisodeUnit | undefined => view.units.find((u) => u.frames.includes(frame));
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

// What a picture's state reads as beside its line.
export function pictureWords(unit: EpisodeUnit): string {
  if (unit.kind === "undesigned") return "Being planned";
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
