// The chapter's lines as a strip under the frame, the way the Figma editor's timeline shows a
// film's parts: each line's frame, small, in the blocks of the script (a picture's lines
// together), the one open marked. A click opens that line in the frame; while a take is recorded
// the line being said is marked and the strip only shows.
import { useEffect, useRef } from "react";
import type { EpisodeFrame, EpisodeView } from "../../api";
import { pictureState, unitOf } from "../../episode";
import { blockName, blocksOf } from "./Blocks";
import { FrameCanvas } from "./FrameCanvas";

export function Timeline({ view, lines, current, recording, onPick }: { view: EpisodeView; lines: EpisodeFrame[]; current: string; recording: boolean; onPick: (frame: string) => void }) {
  const strip = useRef<HTMLDivElement>(null);
  // the open line stays in sight as the frame moves along the chapter (a block, so the effect
  // returns nothing: scrolling may return a promise, which is no cleanup)
  useEffect(() => {
    strip.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [current]);
  return (
    <div ref={strip} className="ep-timeline" role="listbox" aria-label="The chapter's lines" aria-orientation="horizontal">
      {blocksOf(view, lines).map((block) => (
        <div key={block.key} className="ep-timeline-block" data-picture={block.unit ? "" : undefined} data-state={block.unit ? pictureState(block.unit, view) : undefined} title={blockName(block)}>
          {block.lines.map((l) => {
            const n = lines.indexOf(l) + 1;
            return (
              <button
                key={l.id}
                type="button"
                role="option"
                aria-selected={l.id === current}
                aria-label={`Line ${n}: ${l.vo}`}
                className="ep-timeline-line"
                disabled={recording}
                onClick={() => l.id !== current && onPick(l.id)}
              >
                <FrameCanvas view={view} frame={l} unit={unitOf(view, l.id)} label="" takeless />
                <small>{n}</small>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
