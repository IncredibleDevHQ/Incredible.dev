// The plan as a deck. Each chapter is one slide, and its thumbnail is the chapter in small: where
// it sits in the film, its title, and its beats and frames in time. The same thumbnail, larger,
// lays the whole film out on the cover.
import type { KeyboardEvent } from "react";
import type { FrameView, PlanRow } from "../api";
import { isChapter, STATE_WORDS, tone, type ChapterState } from "../plan";
import { MiniTimeline } from "./PlanTimeline";

export function Thumb({
  row,
  frame,
  state,
  notes,
  current,
  large,
  onOpen,
}: {
  row: PlanRow;
  // The chapter's beats and frames, once they are written.
  frame: FrameView | undefined;
  state: ChapterState;
  // Its open notes: on its row of the chapter list, and on its beats and frames.
  notes: number;
  current?: boolean;
  // On the cover, where a thumbnail has room for the chapter's question.
  large?: boolean;
  onOpen: () => void;
}) {
  const data = frame && isChapter(frame.data) ? frame.data : null;
  return (
    <button
      type="button"
      className="th"
      data-size={large ? "large" : undefined}
      aria-current={current ? "page" : undefined}
      title={`${row.label} · ${row.title} · ${STATE_WORDS[state]}`}
      onClick={onOpen}
    >
      <span className="th-top">
        <span className="pl-dot" data-state={tone(state)} />
        <span className="th-label">
          {row.label} · {row.time}
        </span>
        {notes > 0 && <span className="pl-count">{notes}</span>}
      </span>
      <b className="th-title">{row.title}</b>
      {large && row.asks && <span className="th-asks">{row.asks}</span>}
      <span className="th-foot">
        {data ? <MiniTimeline chapter={data} /> : <span className="th-blank" aria-hidden="true" />}
        {row.turn && <span className="th-turn">The turn</span>}
      </span>
    </button>
  );
}

// ↑ and ↓ walk the slides from the filmstrip, as they do in any deck.
export function filmKeys(e: KeyboardEvent<HTMLElement>) {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const slides = [...e.currentTarget.querySelectorAll<HTMLButtonElement>(".th")];
  const focused = slides.findIndex((slide) => slide === document.activeElement);
  const at = focused >= 0 ? focused : slides.findIndex((slide) => slide.getAttribute("aria-current") === "page");
  const next = slides[at + (e.key === "ArrowDown" ? 1 : -1)];
  if (!next) return;
  e.preventDefault();
  next.focus();
  next.click();
}
