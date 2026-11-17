// What the studio reads off an episode: its lines, each line's picture and take, and where a
// chapter stands. The server derives every number (episode_desk.py); nothing here recounts one.
import type { EpisodeChapter, EpisodeFrame, EpisodeLine, EpisodeSettings, EpisodeTake, EpisodeUnit, EpisodeView, LayoutSpot, Level, Presence } from "./api";

export const PRESENCE: Record<Presence, string> = { person: "You", both: "Both", content: "Picture" };
export const LAYOUTS: Record<string, string> = {
  "full-frame": "Full frame",
  "full-frame-close": "Close",
  "framed-on-ground": "Framed",
  "glass-card": "Glass card",
  split: "Split",
  "panel-and-portrait": "Panel and portrait",
  "corner-window": "Corner window",
  "corner-top-right": "Upper corner window",
  "split-presenter-left": "Presenter on the left",
  "floating-card": "Host with a floating card",
  "question-caption": "Question as a caption",
  "avatar-bubble": "Small portrait",
  "graphic-on-ground": "Full screen",
  "number-spotlight": "Number spotlight",
  "chapter-banner": "Chapter banner",
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
// What each way in does, as the film moves the picture (`episode.film`); how long it takes comes with the options.
export const MOVES: Record<string, string> = {
  cut: "There at once, on the word.",
  push: "Slides in from the right as the picture before slides out to the left.",
  crossfade: "The picture before fades out as this one fades in.",
  "zoom-through": "The picture before grows as it fades, and this one grows into its place.",
};

// Whole seconds first, so 59.6 reads 1:00 and never 0:60.
export const mmss = (seconds: number) => {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
};
export const linesOf = (chapter: EpisodeChapter): EpisodeFrame[] => chapter.beats.flatMap((b) => b.frames);
export const chapterName = (chapter: EpisodeChapter) => CHAPTERS[chapter.type ?? ""] ?? "Chapter";
export const unitOf = (view: EpisodeView, frame: string): EpisodeUnit | undefined => view.units.find((u) => u.frames.includes(frame));
export const allLines = (view: EpisodeView): { chapter: string; line: EpisodeFrame }[] => (view.plan?.chapters ?? []).flatMap((c) => linesOf(c).map((line) => ({ chapter: c.id, line })));
// The lines a layout set for a chapter (or the whole film) reaches: the ones of that presence.
export const linesIn = (view: EpisodeView, presence: Presence, chapter?: string) => allLines(view).filter((x) => x.line.presence === presence && (!chapter || x.chapter === chapter));
export const takeOf = (view: EpisodeView, chapter: string): EpisodeTake | undefined => view.takes.find((t) => t.kept && t.chapter === chapter && !t.frame);
export const clockLine = (view: EpisodeView, frame: string): EpisodeLine | undefined => view.clock?.lines.find((l) => l.frame === frame);
export const spotOf = (view: EpisodeView, layout: string): LayoutSpot => view.options.geometry.layouts[layout] ?? view.options.geometry.layouts["graphic-on-ground"];

export function frameSpot(view: EpisodeView, frame: EpisodeFrame): LayoutSpot {
  const spot = spotOf(view, frame.layout);
  return frame.window ? { ...spot, person: frame.window.box, person_radius: frame.window.radius } : spot;
}

// Immediate feedback while a range input is being dragged. The saved box comes from the renderer.
export function resizePresenter(view: EpisodeView, frame: EpisodeFrame, percent: number): EpisodeFrame {
  const spot = spotOf(view, frame.layout);
  if (!spot.person) return frame;
  const [x, y, w, h] = spot.person;
  const [frameWidth, frameHeight] = view.options.geometry.frame;
  let width = Math.min(frameWidth, Math.round(w * percent / 100));
  let height = Math.min(frameHeight, Math.round(h * percent / 100));
  const shape = frame.picked?.window_shape;
  if (shape === "circle") width = height = Math.min(width, height);
  const radius = shape === "circle" ? Math.floor(width / 2)
    : shape === "rectangle" ? 0
    : shape === "rounded" ? Math.round(Math.min(width, height) / 10)
    : spot.person_radius;
  const left = Math.min(frameWidth - width, Math.max(0, x + Math.floor((w - width) / 2)));
  const top = Math.min(frameHeight - height, Math.max(0, y + Math.floor((h - height) / 2)));
  return { ...frame, window: { box: [left, top, width, height], radius } };
}

// Where one picture stands: not asked for yet, on its way, its stills waiting for a go, made,
// out of date, or stopped until someone asks again. Out of date is a picture made for the plan as
// it was (another frame, kind or level), or a line given a picture that waits for the writer:
// both wait for the person to apply their changes, since nothing is drawn while they try picks.
// "changed": drawn from the plan as it was (out of date); "reworded": current, but made for
// words its lines no longer say.
export type PictureState = "planned" | "making" | "go" | "made" | "changed" | "reworded" | "failed";
export function pictureState(unit: EpisodeUnit, view?: EpisodeView): PictureState {
  const p = unit.picture;
  if (unit.kind === "undesigned") return view?.waiting.some((w) => unit.frames.includes(w.line)) ? "changed" : "making";
  if (p.status === "none") return "planned";
  if (p.status === "failed") return "failed";
  if (p.status === "made" || p.status === "go") return p.stale ? "changed" : p.reworded ? "reworded" : p.status;
  return "making";
}

// Where a chapter stands, as its slide and its row read.
export type ChapterState = "planned" | "making" | "go" | "changed" | "reworded" | "failed" | "ready" | "recorded";
export function chapterState(view: EpisodeView, chapter: EpisodeChapter): ChapterState {
  if (takeOf(view, chapter.id)) return "recorded";
  const states = new Set(view.units.filter((u) => u.chapter === chapter.id).map((u) => pictureState(u, view)));
  for (const state of ["go", "making", "changed", "reworded", "failed", "planned"] as const) if (states.has(state)) return state;
  return "ready";
}
export const STATE_WORDS: Record<ChapterState, string> = {
  planned: "Pictures not made yet",
  making: "Pictures being made",
  go: "Stills need your go",
  changed: "Pictures out of date",
  reworded: "Words changed since its pictures",
  failed: "A picture was not made",
  ready: "Ready to record",
  recorded: "Recorded",
};

// How many pictures stand where: of the film, or of one chapter.
export function pictureCount(view: EpisodeView, chapter?: string) {
  const all = view.units.filter((u) => u.kind === "picture" && (!chapter || u.chapter === chapter));
  const count: Record<PictureState, number> = { planned: 0, making: 0, go: 0, made: 0, changed: 0, reworded: 0, failed: 0 };
  for (const u of all) count[pictureState(u, view)] += 1;
  return { all: all.length, ...count };
}

// What a picture's state reads as on its block.
// What each way of making a picture is called where a person meets it: drawn at once from the
// plan, or as motion graphics, each line planned as a shot first.
export const LEVEL_NAMES: Record<Level, string> = { simple: "Simple", rich: "Motion graphics" };
// The voice that reads the film, in the words the studio uses for it.
export const voiceName = (settings: EpisodeSettings) =>
  settings.voice === "local" ? "Local narrator" : settings.voice === "narrator" ? (settings.narrator?.name ?? "ElevenLabs") : settings.presenter === "off" ? "Recorded" : "Your voice";

export function pictureWords(unit: EpisodeUnit, view?: EpisodeView): string {
  if (unit.kind === "undesigned") return pictureState(unit, view) === "changed" ? "Waits for the writer" : "Being planned";
  const p = unit.picture;
  if (p.status === "none") return "Not made yet";
  if (p.status === "failed") return "Not made";
  if ((p.status === "made" || p.status === "go") && p.stale) return "Out of date";
  if ((p.status === "made" || p.status === "go") && p.reworded) return "Made for other words";
  if (p.status === "go") return "Needs your go";
  if (p.status === "made") return "Made";
  if (p.status === "queued") return "Waiting its turn";
  if (p.status === "posing") return "Taking its stills";
  return p.level === "rich" && !p.motion ? "Planning each shot" : "Being drawn";
}

// The agent picked last on this computer (for a new episode, or as a film's agent), so the next
// episode starts with it and not with whichever is listed first.
const WRITER_KEY = "episode-writer";
export function lastWriter(): string {
  try {
    return localStorage.getItem(WRITER_KEY) ?? "";
  } catch {
    return "";
  }
}
export function keepWriter(id: string): void {
  try {
    localStorage.setItem(WRITER_KEY, id);
  } catch {
    // a browser that keeps nothing: the next episode starts with the first agent that is ready
  }
}

// A box of the 1920 by 1080 frame as CSS on a stage of any size.
export function boxStyle(box: [number, number, number, number], frame: [number, number], radius = 0): React.CSSProperties {
  const [x, y, w, h] = box;
  return {
    left: `${(x / frame[0]) * 100}%`,
    top: `${(y / frame[1]) * 100}%`,
    width: `${(w / frame[0]) * 100}%`,
    height: `${(h / frame[1]) * 100}%`,
    borderRadius: `calc(${Math.min(radius, w / 2, h / 2) / frame[0]} * 100cqw)`,
  };
}
