// A range on one track: a least and a most that never come closer than `gap`. Each end is a
// native slider, so the keyboard and a screen reader have both. Only the thumbs take the
// pointer; a press on the track moves the nearer end there.
import type { CSSProperties, PointerEvent } from "react";

// The thumb's width, as app.css draws it: a native thumb's centre travels the track less this.
const THUMB = 16;

type Props = {
  min: number;
  max: number;
  step: number;
  gap: number;
  value: [number, number];
  onChange: (value: [number, number]) => void;
  // What each end is called, and how a value is said.
  labels: [string, string];
  format: (value: number) => string;
};

export function RangeSlider({ min, max, step, gap, value, onChange, labels, format }: Props) {
  const [low, high] = value;
  const share = (v: number) => (v - min) / (max - min);
  const setLow = (v: number) => onChange([Math.max(min, Math.min(v, high - gap)), high]);
  const setHigh = (v: number) => onChange([low, Math.min(max, Math.max(v, low + gap))]);
  const press = (e: PointerEvent<HTMLSpanElement>) => {
    if (e.target !== e.currentTarget) return;
    const box = e.currentTarget.getBoundingClientRect();
    const along = Math.min(1, Math.max(0, (e.clientX - box.left - THUMB / 2) / (box.width - THUMB)));
    const at = min + Math.round((along * (max - min)) / step) * step;
    if (Math.abs(at - low) <= Math.abs(at - high)) setLow(at);
    else setHigh(at);
  };
  return (
    <span className="range2" style={{ "--from": share(low), "--to": share(high) } as CSSProperties} onPointerDown={press}>
      <input type="range" aria-label={labels[0]} aria-valuetext={format(low)} min={min} max={max} step={step} value={low} onChange={(e) => setLow(Number(e.target.value))} />
      <input type="range" aria-label={labels[1]} aria-valuetext={format(high)} min={min} max={max} step={step} value={high} onChange={(e) => setHigh(Number(e.target.value))} />
    </span>
  );
}
