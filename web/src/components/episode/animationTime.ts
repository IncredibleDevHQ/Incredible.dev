import type { EpisodeFrame, EpisodeUnit } from "../../api";

// Narration edits move the spoken clock. The encoded clip keeps its original beat spans.
export function animationTime(
  frame: Pick<EpisodeFrame, "id" | "start" | "seconds">,
  unit: Pick<EpisodeUnit, "start" | "picture"> | undefined,
  elapsed: number,
  duration: number,
): number {
  const saved = unit?.picture.generation?.clip_lines?.[frame.id];
  const start = saved?.[0] ?? Math.max(0, frame.start - (unit?.start ?? frame.start));
  const end = saved?.[1] ?? start + frame.seconds;
  const progress = Math.max(0, Math.min(1, elapsed / Math.max(0.001, duration)));
  return start + Math.max(0, end - start) * progress;
}
