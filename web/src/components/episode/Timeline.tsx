// The chapter along its own clock, after the Figma editor's timeline strip under the page. As
// the strip shows each node as a card holding a small screen with its kind, every block of the
// script is a tile as long as its lines, its kind on a small screen (dark for the block open) and,
// where the tile is wide enough, its name; where a block brings a picture in, the join before it
// carries a mark of how it comes in (a cut, a push, a crossfade, a zoom), as the strip marks the
// transition between two nodes, and a click on it opens that choice. What the film shows that no
// line says stands at the strip's ends, as the strip opens on its Title: the film's title before
// the first chapter, a chapter's card, the end card after the last. Under the tiles each line is a
// span as long as it lasts (from the take once there is one, from the plan before), under a ruler
// of times. The playhead stands on the open line, or on the moment playing while a line plays. A
// click on a line opens it, a click on a block opens its first line, and every tile and span says
// when it starts and how long it runs. Tall, it shows each line's frame in its span where the span
// is wide enough to hold one. Each beat's tile carries at most one quiet mark, as a slide's
// thumbnail marks its transition: the most pressing of a picture that was not made, one that
// needs the person's go, one being made and one out of date, else that it is motion graphics.
// A beat whose picture is being made turns its mark, runs a line along its foot however narrow
// the tile is, and where it is wide enough says what its builder is on.
import { Blend, Film, MoveRight, Pause, Scissors, ZoomIn, type LucideIcon } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import type { EpisodeChapter, EpisodeFrame, EpisodeView } from "../../api";
import { clockLine, doingNow, markOf, mmss, pictureState, TRANSITIONS, unitOf } from "../../episode";
import { blockName, blocksOf, KindIcon, type Block } from "./Blocks";
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

// The mark of each way a picture comes in.
const MOVE_ICONS: Record<string, LucideIcon> = { cut: Scissors, push: MoveRight, crossfade: Blend, "zoom-through": ZoomIn, none: Pause };


// How a block's picture comes in, where the block brings one in: on the picture's first line, when
// that line is not said to camera (the Transition panel's own rule).
function wayIn(block: Block): string | undefined {
  const lead = block.lines[0];
  const u = block.unit;
  if (u?.kind !== "picture" || u.frames[0] !== lead.id || lead.presence === "person") return undefined;
  const planned = lead.transition && lead.transition !== "none" ? lead.transition : "cut";
  return lead.picked?.transition ?? planned;
}

type Cap = { name: string; said: string };

// What the film shows at the chapter's ends that no line says: before the first chapter its
// title, over a chapter's first words its card, after the last chapter the end card.
function capsOf(view: EpisodeView, chapter: EpisodeChapter): { start?: Cap; end?: Cap } {
  const marks = view.clock?.marks ?? [];
  const chapters = view.clock?.chapters ?? [];
  const sting = chapters[0]?.id === chapter.id ? marks.find((m) => m.mark === "title-sting") : undefined;
  const card = marks.find((m) => m.mark === "chapter-card" && m.chapter === chapter.id);
  const end = chapters[chapters.length - 1]?.id === chapter.id ? marks.find((m) => m.mark === "end-card") : undefined;
  const s = (seconds: number) => `${Math.round(seconds)} s`;
  return {
    start: sting
      ? { name: "Title", said: `The film's title, ${s(sting.seconds)} before the first line` }
      : card
        ? { name: "Chapter card", said: `The chapter's card, over its first ${s(card.seconds)}` }
        : undefined,
    end: end ? { name: "End card", said: `The end card, ${s(end.seconds)} after the last line` } : undefined,
  };
}

export function Timeline({
  view,
  chapter,
  lines,
  current,
  playhead,
  recording,
  tall,
  onPick,
  onJoin,
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
  // opens how the picture that line brings in comes in
  onJoin?: (frame: string) => void;
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
  const caps = capsOf(view, chapter);
  // the script's blocks along the clock, from the start of their first line to the end of their
  // last, how each one's picture comes in, and each line's block, for its tint: a picture's
  // lines together, a run said to camera, and how its picture stands
  const spanOf = new Map(spans.map((s) => [s.line.id, s]));
  const blocks = blocksOf(view, lines).map((block, i) => {
    const mine = block.lines.flatMap((l) => spanOf.get(l.id) ?? []);
    const start = Math.min(...mine.map((s) => s.start));
    const end = Math.max(...mine.map((s) => s.start + s.seconds));
    const mark = markOf(block.unit, view);
    return {
      block,
      name: blockName(block),
      state: block.unit ? pictureState(block.unit, view) : undefined,
      mark,
      // what its builder is on, in a word, while its picture is made
      doing: block.unit && mark?.kind === "making" ? doingNow(block.unit, view) : "",
      way: i > 0 ? wayIn(block) : undefined,
      start,
      seconds: end - start,
      from: mine[0]?.n ?? 0,
      to: mine[mine.length - 1]?.n ?? 0,
    };
  });
  const blockOf = new Map<string, { name: string; picture: boolean; state?: string; first: boolean }>();
  for (const b of blocks) b.block.lines.forEach((l, i) => blockOf.set(l.id, { name: b.name, picture: Boolean(b.block.unit), state: b.state, first: i === 0 }));
  const linesSaid = (from: number, to: number) => (from === to ? `line ${from}` : `lines ${from} to ${to}`);
  const cap = (c: Cap) => (
    <span className="ep-timeline-cap" title={c.said} aria-label={c.said}>
      {c.name}
    </span>
  );
  return (
    <div className="ep-timeline" data-tall={tall || undefined} role="group" aria-label={`The chapter on its clock, ${mmss(total)} long`}>
      {caps.start && cap(caps.start)}
      <div className="ep-timeline-track">
        <div className="ep-timeline-ruler" aria-hidden="true">
          {ticks.map((t) => (
            <span key={t} style={{ left: pct(t) }}>
              {mmss(t)}
            </span>
          ))}
        </div>
        {/* a mouse's way to a block and its join: the keyboard has each line, which says its block,
            and the pop-up's Transition panel */}
        <div className="ep-timeline-blocks" role="group" aria-label="The chapter's blocks">
          {blocks.map((b, i) => {
            const px = (b.seconds / total) * width;
            const first = b.block.lines[0].id;
            // wide enough, a beat being made says what its builder is on beside its turning mark
            const says = Boolean(b.doing) && px >= 210;
            return (
              <button
                key={b.block.key}
                type="button"
                tabIndex={-1}
                className="ep-timeline-block"
                data-picture={Boolean(b.block.unit) || undefined}
                data-state={b.state}
                data-open={b.block.lines.some((l) => l.id === current) || undefined}
                data-after-join={Boolean(b.way) || undefined}
                data-before-join={Boolean(blocks[i + 1]?.way) || undefined}
                aria-label={`${b.name}, ${linesSaid(b.from, b.to)}, ${mmss(b.start)} to ${mmss(b.start + b.seconds)}${b.mark ? `, ${b.mark.said}` : ""}`}
                title={`${b.name} · ${linesSaid(b.from, b.to)} · ${mmss(b.start)}–${mmss(b.start + b.seconds)}${b.mark ? ` · ${b.mark.said}` : ""}`}
                disabled={recording}
                style={{ left: pct(b.start), width: `max(2px, calc(${pct(b.seconds)} - 3px))` }}
                onClick={() => first !== current && onPick(first)}
              >
                {px >= 34 && (
                  <span className="ep-timeline-screen">
                    <KindIcon block={b.block} />
                  </span>
                )}
                {px >= 124 && <span className="ep-timeline-name">{b.name}</span>}
                {says && (
                  <span className="ep-timeline-doing">
                    <i className="ep-working" aria-hidden="true" />
                    {b.doing}
                  </span>
                )}
                {b.mark && px >= 34 && !says && (
                  <i className="ep-timeline-mark" data-mark={b.mark.kind} aria-hidden="true">
                    {b.mark.kind === "rich" && <Film />}
                  </i>
                )}
              </button>
            );
          })}
          {blocks.map((b) => {
            if (!b.way) return null;
            const Icon = MOVE_ICONS[b.way] ?? Scissors;
            const how = TRANSITIONS[b.way] ?? b.way;
            const lead = b.block.lines[0];
            return (
              <button
                key={`in-${b.block.key}`}
                type="button"
                tabIndex={-1}
                className="ep-timeline-join"
                data-picked={Boolean(lead.picked?.transition) || undefined}
                aria-label={`How the ${b.name.toLowerCase()} comes in: ${how}`}
                title={`${how} into the ${b.name.toLowerCase()} · line ${b.from}`}
                disabled={recording || !onJoin}
                style={{ left: pct(b.start) }}
                onClick={() => onJoin?.(lead.id)}
              >
                <Icon aria-hidden="true" />
              </button>
            );
          })}
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
                aria-label={`Line ${s.n}${block ? `, ${block.name}` : ""}, ${mmss(s.start)} to ${mmss(s.start + s.seconds)}: ${s.line.vo}`}
                title={`Line ${s.n}${block ? ` · ${block.name}` : ""} · ${mmss(s.start)}–${mmss(s.start + s.seconds)} · ${Math.round(s.seconds)} s`}
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
        </div>
        <i className="ep-timeline-head" aria-hidden="true" style={{ left: pct(at) }} />
      </div>
      {caps.end && cap(caps.end)}
    </div>
  );
}
