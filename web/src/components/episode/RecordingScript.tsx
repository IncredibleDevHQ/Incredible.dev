import { useEffect, useRef } from "react";

// Follow beat changes without pulling the reader back on every word tick.
export function RecordingScript({ lines, current, elapsed, seconds }: {
  lines: { id: string; vo: string }[];
  current: string;
  elapsed: number;
  seconds: number;
}) {
  const list = useRef<HTMLOListElement>(null);
  const active = useRef<HTMLLIElement>(null);
  useEffect(() => {
    const container = list.current;
    const item = active.current;
    if (!container || !item) return;
    const box = container.getBoundingClientRect();
    const row = item.getBoundingClientRect();
    if (row.top < box.top || row.bottom > box.bottom) {
      container.scrollTop += row.top - box.top;
    }
  }, [current]);
  const currentIndex = lines.findIndex(line => line.id === current);
  return <ol ref={list} className="ep-say-lines" aria-label="Chapter script">
    {lines.map((line, index) => {
      const isCurrent = line.id === current;
      const words = line.vo.split(/(\s+)/);
      const wordIndex = Math.max(0, Math.min(words.length - 1, Math.floor(elapsed / Math.max(0.1, seconds) * Math.ceil(words.length / 2)) * 2));
      return <li key={line.id} ref={isCurrent ? active : undefined} aria-current={isCurrent ? "step" : undefined} data-past={index < currentIndex || undefined}>
        <div className="ep-kicker">Line {index + 1}{isCurrent ? " · Read now" : ""}</div>
        <p>{isCurrent ? words.map((word, i) => <span key={i} data-active={i === wordIndex || undefined}>{word}</span>) : line.vo}</p>
      </li>;
    })}
  </ol>;
}
