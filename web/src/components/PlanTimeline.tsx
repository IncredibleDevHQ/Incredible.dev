// A plan in time. One chapter's beats and frames laid out on its clock, with what each frame
// shows, says, puts on screen and sounds like on its own track: a line is drawn as long as it
// takes to say, so the air left in a frame is the gap after it, and a line that runs over is
// seen running over. The whole episode on one strip, to move between chapters. And a chapter's
// beats and frames as two thin rows, for its thumbnail.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { PlanBeat, PlanRow, PlanShot } from "../api";
import { chapterState, isChapter, STATE_WORDS, tone, type Chapter, type Stage } from "../plan";
import type { FrameView } from "../api";

// How wide a second is drawn when the chapter is zoomed in to read, the least it can be drawn
// with its lines still legible when the whole chapter is fitted to its slide, and how long a
// line needs of its frame beyond the words (the same half second the checks hold it to).
const READ_SCALE = 30;
const FIT_SCALE_LEAST = 14;
const SPARE = 0.5;
const TRACKS = ["Beats", "Picture", "Voice", "On screen", "Sound"] as const;

const mmss = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;

// The marks on a ruler: every five seconds when there is room for the labels, else every ten.
function ticks(start: number, length: number, scale: number) {
  const step = scale >= 9 ? 5 : scale >= 4.5 ? 10 : scale >= 1.6 ? 30 : 60;
  const out: number[] = [];
  for (let t = Math.ceil(start / step) * step; t < start + length - step / 3; t += step) out.push(t);
  return out;
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const seen = new ResizeObserver(() => setWidth(el.clientWidth));
    seen.observe(el);
    return () => seen.disconnect();
  }, []);
  return [ref, width] as const;
}

export function ChapterTimeline({
  chapter,
  selected,
  noted,
  onPick,
  meta,
}: {
  chapter: Chapter;
  // The beat or frame picked, by its id.
  selected: string;
  // The open notes on a row.
  noted: (row: string) => number;
  onPick: (row: string) => void;
  // What heads the timeline, in place of its own name: the chapter's counts on its slide.
  meta?: ReactNode;
}) {
  // The whole chapter on its slide when its lines stay legible that small; zoomed in to read
  // when they would not. Whoever picks one keeps it.
  const [mode, setMode] = useState<"read" | "fit" | null>(null);
  const [ref, width] = useWidth();
  const { start, seconds, beats } = chapter;
  const fit = width > 0 && seconds > 0 ? width / seconds : READ_SCALE;
  const zoomed = mode ? mode === "read" : fit < FIT_SCALE_LEAST;
  const scale = zoomed ? Math.max(fit, READ_SCALE) : fit;
  const at = (t: number) => (t - start) * scale;
  const span = (from: number, length: number) => ({ left: at(from), width: Math.max(length * scale - 2, 4) });
  const owner = beats.find((b) => b.id === selected || b.shots?.some((s) => s.id === selected));
  const picked: PlanBeat | PlanShot | undefined = owner?.shots?.find((s) => s.id === selected) ?? owner;

  // Keep what is picked in view as the selection moves along the clock.
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[aria-pressed="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [selected, zoomed, ref]);

  const mark = (id: string) => (noted(id) > 0 ? <i className="tl-note" title={`${noted(id)} open ${noted(id) === 1 ? "note" : "notes"}`} /> : null);
  return (
    <section className="tl" data-mode={zoomed ? "read" : "fit"} aria-label="The chapter in time">
      <header className="tl-head">
        {meta ?? <b>In time</b>}
        <span className="pl-soft tl-hint">A line is drawn as long as it takes to say. ← → step through.</span>
        <span className="seg" role="group" aria-label="How much of the chapter to show">
          <button type="button" aria-pressed={!zoomed} onClick={() => setMode("fit")}>
            Fit
          </button>
          <button type="button" aria-pressed={zoomed} onClick={() => setMode("read")}>
            Read
          </button>
        </span>
      </header>
      <div className="tl-body">
        <div className="tl-names" aria-hidden="true">
          <span />
          {TRACKS.map((name) => (
            <span key={name} data-track={name}>
              {name}
            </span>
          ))}
        </div>
        <div className="tl-scroll" ref={ref}>
          <div className="tl-lanes" style={{ width: seconds * scale }}>
            {picked && <span className="tl-now" style={span(picked.start, picked.seconds)} />}
            <div className="tl-ruler">
              {ticks(start, seconds, scale).map((t) => (
                <span key={t} style={{ left: at(t) }}>
                  {mmss(t)}
                </span>
              ))}
            </div>
            <div className="tl-track" data-track="Beats">
              {beats.map((b) => (
                <button type="button" key={b.id} className="tl-beat" style={span(b.start, b.seconds)} aria-pressed={selected === b.id} title={`${b.id} · ${b.title} · ${b.time}`} onClick={() => onPick(b.id)}>
                  <b>
                    <span className="mono">{b.id}</span> {b.title}
                    {mark(b.id)}
                  </b>
                  <span>{b.takeaway}</span>
                </button>
              ))}
            </div>
            <div className="tl-track" data-track="Picture">
              {beats.map((b) =>
                b.shots?.length ? (
                  b.shots.map((s) => (
                    <button type="button" key={s.id} className={`tl-shot ${b.stale ? "stale" : ""}`} style={span(s.start, s.seconds)} aria-pressed={selected === s.id} title={`${s.id} · ${s.move} · ${s.time}\n${s.shows}`} onClick={() => onPick(s.id)}>
                      <b>
                        <span className="mono">{s.id}</span> {s.move}
                        {mark(s.id)}
                      </b>
                      <span>{s.shows}</span>
                    </button>
                  ))
                ) : (
                  <span key={b.id} className="tl-wait" style={span(b.start, b.seconds)}>
                    Frames to come
                  </span>
                ),
              )}
            </div>
            <div className="tl-track" data-track="Voice">
              {beats.flatMap((b) =>
                b.shots?.length
                  ? b.shots
                      .filter((s) => s.vo)
                      .map((s) => (
                        <button type="button" key={s.id} className={`tl-line ${s.speaks + SPARE > s.seconds + 0.05 ? "over" : ""}`} style={span(s.start, s.speaks)} title={`${s.vo}\n${s.speaks} s to say, in a ${s.seconds} s frame`} onClick={() => onPick(s.id)}>
                          <span>{s.vo}</span>
                        </button>
                      ))
                  : b.says
                    ? [
                        <button type="button" key={b.id} className={`tl-line ${b.speaks + SPARE > b.seconds + 0.05 ? "over" : ""}`} style={span(b.start, b.speaks)} title={`${b.says}\n${b.speaks} s to say, in a ${b.seconds} s beat`} onClick={() => onPick(b.id)}>
                          <span>{b.says}</span>
                        </button>,
                      ]
                    : [],
              )}
            </div>
            <div className="tl-track" data-track="On screen">
              {beats.flatMap((b) =>
                (b.shots ?? [])
                  .filter((s) => s.on)
                  .map((s) => {
                    const lands = s.at ?? 0;
                    return (
                      <button type="button" key={s.id} className={`tl-words ${s.reads > s.seconds - lands + 0.05 ? "over" : ""}`} style={span(s.start + lands, s.seconds - lands)} title={`“${s.on}” lands ${lands} s in and holds ${Math.round((s.seconds - lands) * 10) / 10} s; it needs ${s.reads} s to read`} onClick={() => onPick(s.id)}>
                        {s.on}
                      </button>
                    );
                  }),
              )}
            </div>
            <div className="tl-track" data-track="Sound">
              {beats.flatMap((b) =>
                (b.shots ?? [])
                  .filter((s) => s.sound)
                  .map((s) => (
                    <button type="button" key={s.id} className="tl-sound" style={span(s.start, s.seconds)} title={s.sound} onClick={() => onPick(s.id)}>
                      {s.sound}
                    </button>
                  )),
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// The whole episode on one strip: its parts by length, and under each the beats and frames it
// has so far. A part opens its chapter.
export function EpisodeTimeline({
  listed,
  chapterOf,
  topSigned,
  stageOf,
  onOpen,
}: {
  listed: PlanRow[];
  chapterOf: (row: PlanRow) => FrameView | undefined;
  topSigned: boolean;
  stageOf: (name: string) => Stage;
  onOpen: (row: PlanRow) => void;
}) {
  const [ref, width] = useWidth();
  const total = listed.reduce((n, c) => n + (c.seconds ?? 0), 0);
  if (!total) return null;
  const scale = width / total;
  const span = (from: number, length: number) => ({ left: from * scale, width: Math.max(length * scale - 2, 2) });
  return (
    <section className="tl tl-episode" aria-label="The episode in time">
      <div className="tl-scroll" ref={ref}>
        <div className="tl-lanes" style={{ width: "100%" }}>
          <div className="tl-ruler">
            {ticks(0, total, scale).map((t) => (
              <span key={t} style={{ left: t * scale }}>
                {mmss(t)}
              </span>
            ))}
          </div>
          <div className="tl-track" data-track="Parts">
            {listed.map((c) => {
              const state = chapterState(chapterOf(c), topSigned, stageOf(c.label));
              return (
                <button type="button" key={c.id} className="tl-part" data-state={tone(state)} style={span(c.start ?? 0, c.seconds ?? 0)} title={`${c.label} · ${c.title} · ${c.time} · ${STATE_WORDS[state]}${c.turn ? `\nThe turn: ${c.turn}` : ""}`} onClick={() => onOpen(c)}>
                  <b>
                    {c.label.replace("Chapter ", "")}
                    {c.turn && <i className="tl-turn">The turn</i>}
                  </b>
                  <span>{c.title}</span>
                </button>
              );
            })}
          </div>
          <div className="tl-track" data-track="Beats and frames">
            {listed.flatMap((c) => {
              const data = chapterOf(c)?.data;
              if (!isChapter(data)) return [<span key={c.id} className="tl-wait" style={span(c.start ?? 0, c.seconds ?? 0)} />];
              return data.beats.flatMap((b) => [
                <span key={b.id} className="tl-mini beat" style={span(b.start, b.seconds)} />,
                ...(b.shots ?? []).map((s) => <span key={s.id} className={`tl-mini ${b.stale ? "stale" : ""}`} style={span(s.start, s.seconds)} />),
              ]);
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

// A chapter in small, for its thumbnail: its beats over its frames, each where it starts and as
// wide as it runs.
export function MiniTimeline({ chapter }: { chapter: Chapter }) {
  const { start, seconds, beats } = chapter;
  if (!seconds) return null;
  const span = (from: number, length: number) => ({ left: `${((from - start) / seconds) * 100}%`, width: `calc(${(length / seconds) * 100}% - 1.5px)` });
  return (
    <span className="th-time" aria-hidden="true">
      <span>
        {beats.map((b) => (
          <i key={b.id} className="beat" style={span(b.start, b.seconds)} />
        ))}
      </span>
      <span>
        {beats.flatMap((b) => (b.shots ?? []).map((s) => <i key={s.id} className={b.stale ? "stale" : undefined} style={span(s.start, s.seconds)} />))}
      </span>
    </span>
  );
}

// The frame after or before the one picked, across the chapter's beats. A beat with no frames
// yet stands in for them, so the arrow keys never skip it; a beat picked as a whole steps onto
// its own first frame.
export function step(chapter: Chapter, selected: string, by: 1 | -1): string {
  const stops = chapter.beats.flatMap((b) => (b.shots?.length ? b.shots.map((s) => s.id) : [b.id]));
  const clamp = (n: number) => stops[Math.min(Math.max(n, 0), stops.length - 1)] ?? selected;
  const at = stops.indexOf(selected);
  if (at >= 0) return clamp(at + by);
  const first = chapter.beats.find((b) => b.id === selected)?.shots?.[0]?.id;
  if (!first) return clamp(0);
  return by === 1 ? first : clamp(stops.indexOf(first) - 1);
}
