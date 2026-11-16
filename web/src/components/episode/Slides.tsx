// The chapters as slides down the left of a chapter's page, the way a deck lists its slides:
// each chapter's first picture as it stands now (its still once it is posed, the layout's boxes
// before that), its question, and where it stands. One click opens a chapter.
import { useEffect, useRef } from "react";
import type { EpisodeChapter, EpisodeView } from "../../api";
import { boxStyle, chapterName, chapterState, linesOf, spotOf, STATE_WORDS, unitOf } from "../../episode";

export function Slides({ view, at, onAt }: { view: EpisodeView; at: string; onAt: (chapter: string) => void }) {
  const chapters = view.plan?.chapters ?? [];
  const current = useRef<HTMLButtonElement>(null);
  // the open chapter is in sight when the page opens, however far down the film it is
  useEffect(() => current.current?.scrollIntoView({ block: "nearest" }), [at]);
  return (
    <nav className="ep-slides" aria-label="Chapters">
      <ol>
        {chapters.map((c, i) => {
          const state = view.approved ? chapterState(view, c) : "ready";
          const open = c.id === at;
          return (
            <li key={c.id}>
              <button ref={open ? current : undefined} type="button" className="ep-slide" aria-current={open || undefined} data-state={state} onClick={() => !open && onAt(c.id)}>
                <SlidePicture view={view} chapter={c} />
                <span className="ep-slide-words">
                  <b>{i + 1}</b>
                  <span>{c.question}</span>
                </span>
                <small>
                  {chapterName(c)} · {view.approved ? STATE_WORDS[state] : "Planned"}
                </small>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// The chapter's first line with a picture, as the film frames it.
function SlidePicture({ view, chapter }: { view: EpisodeView; chapter: EpisodeChapter }) {
  const lines = linesOf(chapter);
  const line = lines.find((l) => l.presence !== "person") ?? lines[0];
  const spot = spotOf(view, line.layout);
  const size = view.options.geometry.frame;
  const still = unitOf(view, line.id)?.picture.stills[line.id];
  const picture = line.presence !== "person" ? spot.picture : null;
  const person = line.presence !== "content" ? spot.person : null;
  return (
    <span className="ep-thumb ep-slide-pic" aria-hidden="true">
      {picture && (
        <i className="pic" data-glass={spot.glass || undefined} style={boxStyle(picture, size, spot.picture_radius)}>
          {still && <img src={still.url} alt="" loading="lazy" />}
        </i>
      )}
      {person && <i className="who" style={boxStyle(person, size, spot.person_radius)} />}
    </span>
  );
}
