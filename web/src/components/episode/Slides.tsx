// The film and its chapters as slides down the left of the studio, the way a deck lists its
// slides: the film first, as its title card, then each chapter's first picture as it stands now
// (its still once it is posed, the layout's boxes before that), its question, and where it
// stands. One click opens the film or a chapter.
import { Clapperboard } from "lucide-react";
import { useEffect, useRef } from "react";
import type { EpisodeChapter, EpisodeView } from "../../api";
import { boxStyle, chapterName, chapterState, linesOf, mmss, spotOf, STATE_WORDS, takeOf, unitOf } from "../../episode";

// Where the studio is when it shows the film rather than one chapter.
export const FILM = "film";

export function Slides({ view, at, onAt }: { view: EpisodeView; at: string; onAt: (to: string) => void }) {
  const chapters = view.plan?.chapters ?? [];
  const current = useRef<HTMLButtonElement>(null);
  // the open slide is in sight when the page opens, however far down the film it is
  // (a block, so the effect returns nothing: scrolling may return a promise, which is no cleanup)
  useEffect(() => {
    current.current?.scrollIntoView({
      block: "nearest", inline: "nearest",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
    });
  }, [at]);
  const film = at === FILM;
  const recorded = chapters.filter((c) => takeOf(view, c.id)).length;
  return (
    <nav className="ep-slides" aria-label="The film and its chapters">
      <header className="ep-rail-head">
        <span>Chapters</span>
        <b>{chapters.length}</b>
      </header>
      <ol>
        <li>
          <button ref={film ? current : undefined} type="button" className="ep-slide" aria-current={film || undefined} onClick={() => !film && onAt(FILM)}>
            <span className="ep-thumb ep-slide-pic ep-cover" aria-hidden="true">
              <b>
                <span>{view.title}</span>
              </b>
            </span>
            <span className="ep-slide-words">
              <b>
                <Clapperboard aria-hidden="true" />
              </b>
              <span>The film</span>
            </span>
            <small>
              {chapters.length} chapters · {mmss(view.clock?.total ?? view.plan?.totals.seconds ?? 0)}
              {view.status === "studio" && ` · ${recorded} recorded`}
            </small>
          </button>
        </li>
        {chapters.map((c, i) => {
          const state = chapterState(view, c);
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
                  {chapterName(c)} · {STATE_WORDS[state]}
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
