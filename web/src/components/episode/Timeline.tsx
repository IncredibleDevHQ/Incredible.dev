// The chapter's lines along its own clock, the way the Figma editor's timeline runs under the
// page: each line a span as long as it lasts (from the take once there is one, from the plan
// before), in the blocks of the script, a picture's lines tinted together. The line open is marked
// and the playhead stands on it, or on the moment playing while a line plays. A click opens a
// line, and every span says when it starts and how long it runs. Tall, it shows each line's frame
// in its span where the span is wide enough to hold one.
import { useLayoutEffect, useRef, useState } from "react";
import type { EpisodeChapter, EpisodeFrame, EpisodeView } from "../../api";
import { clockLine, mmss, pictureState, unitOf } from "../../episode";
import { blocksOf } from "./Blocks";
import { FrameCanvas } from "./FrameCanvas";

export type Span = { line: EpisodeFrame; n: number; start: number; seconds: number };

// Where each line of a chapter falls on the chapter's own clock, in seconds from its start.
export function spansOf(view: EpisodeView, chapter: EpisodeChapter, lines: EpisodeFrame[]): { spans: Span[]; total: number } {
  const own = view.clock?.chapters.find((c) => c.id === chapter.id);
  const first = lines[0]?.start ?? 0;
  const spans = lines.map((line, i) => {
    const c = clockLine(view, line.id);
    return { line, n: i + 1, start: c ? c.start - (own?.start ?? 0) : line.start - first, seconds: c?.seconds ?? line.seconds };
  });
  const end = spans.reduce((most, s) => Math.max(most, s.start + s.seconds), 0);
  return { spans, total: Math.max(own?.seconds ?? 0, end, 1) };
}

// A tick every so many seconds, so the ruler holds about eight.
const STEPS = [1, 2, 5, 10, 15, 30, 60, 120];
const stepFor = (total: number) => STEPS.find((s) => total / s <= 8) ?? 300;

export function Timeline({
  view,
  chapter,
  lines,
  current,
  playhead,
  recording,
  tall,
  onPick,
}: {
  view: EpisodeView;
  chapter: EpisodeChapter;
  lines: EpisodeFrame[];
  current: string;
  // seconds into the chapter where the playhead stands; the open line's start when not given
  playhead?: number | null;
  recording: boolean;
  tall?: boolean;
  onPick: (frame: string) => void;
}) {
  const bar = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = bar.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const watch = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  const { spans, total } = spansOf(view, chapter, lines);
  const pct = (t: number) => `${(Math.min(Math.max(t, 0), total) / total) * 100}%`;
  const open = spans.find((s) => s.line.id === current);
  const at = playhead ?? open?.start ?? 0;
  const step = stepFor(total);
  const ticks = Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step);
  // each line's block, for its tint: a picture's lines together, a run said to camera, and how
  // its picture stands
  const blockOf = new Map<string, { picture: boolean; state?: string; first: boolean }>();
  for (const block of blocksOf(view, lines)) {
    block.lines.forEach((l, i) => blockOf.set(l.id, { picture: Boolean(block.unit), state: block.unit ? pictureState(block.unit, view) : undefined, first: i === 0 }));
  }
  return (
    <div className="ep-timeline" data-tall={tall || undefined} role="group" aria-label={`The chapter on its clock, ${mmss(total)} long`}>
      <div className="ep-timeline-ruler" aria-hidden="true">
        {ticks.map((t) => (
          <span key={t} style={{ left: pct(t) }}>
            {mmss(t)}
          </span>
        ))}
      </div>
      <div ref={bar} className="ep-timeline-bar" role="listbox" aria-orientation="horizontal" aria-label="The chapter's lines">
        {spans.map((s) => {
          const block = blockOf.get(s.line.id);
          const px = (s.seconds / total) * width;
          return (
            <button
              key={s.line.id}
              type="button"
              role="option"
              aria-selected={s.line.id === current}
              aria-label={`Line ${s.n}, ${mmss(s.start)} to ${mmss(s.start + s.seconds)}: ${s.line.vo}`}
              title={`Line ${s.n} · ${mmss(s.start)}–${mmss(s.start + s.seconds)} · ${Math.round(s.seconds)} s`}
              className="ep-timeline-span"
              data-picture={block?.picture || undefined}
              data-state={block?.state}
              data-joins={(block && !block.first) || undefined}
              disabled={recording}
              style={{ left: pct(s.start), width: pct(s.seconds) }}
              onClick={() => s.line.id !== current && onPick(s.line.id)}
            >
              {tall && px >= 112 && <FrameCanvas view={view} frame={s.line} unit={unitOf(view, s.line.id)} label="" takeless />}
              {px >= 18 && <small>{s.n}</small>}
            </button>
          );
        })}
        <i className="ep-timeline-head" aria-hidden="true" style={{ left: pct(at) }} />
      </div>
    </div>
  );
}
