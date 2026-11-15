// What a person can choose for the picked line, in the order they would think of it: the frame
// (one pick sets who has it and the layout), then the picture it shows. A pick is the line's
// own until it is widened, in one click, to the picture's other lines, the chapter or the film.
import { useEffect, useState } from "react";
import { api, type EpisodeChapter, type EpisodeChoices, type EpisodeFrame, type EpisodeUnit, type EpisodeView, type Level, type Presence } from "../../api";
import { allLines, LAYOUTS, linesIn, LOOKS, PICTURES, redrawnBy, TRANSITIONS } from "../../episode";
import { SegmentedControl } from "../SegmentedControl";
import { Tooltip } from "../Tooltip";
import type { Run } from "./Ask";
import { LayoutThumb } from "./Stage";

const WHO: Record<Presence, string> = { person: "You", both: "You and the picture", content: "The picture alone" };
const ORDER: Record<Presence, number> = { person: 0, both: 1, content: 2 };

export function Choices({
  view,
  chapter,
  line,
  unit,
  run,
  busy,
  onFilm,
  onAskPicture,
}: {
  view: EpisodeView;
  chapter: EpisodeChapter;
  line: EpisodeFrame;
  unit?: EpisodeUnit;
  run: Run;
  busy: boolean;
  onFilm: () => void;
  onAskPicture: () => void;
}) {
  const presenterOff = view.settings.presenter === "off";
  const theme = view.options.themes.find((t) => t.id === view.settings.theme);
  const choose = (body: EpisodeChoices) => run(() => api.chooseEpisode(view.id, body));

  // The look's layouts, you first, then you with a picture, then the picture alone. The line's
  // own layout is always among them, even one the look no longer has.
  const kit = [...(theme?.kit ?? [])].sort((a, b) => ORDER[a.presence] - ORDER[b.presence]);
  const frames = kit.some((k) => k.layout === line.layout) ? kit : [{ layout: line.layout, presence: line.presence }, ...kit];
  const setFrame = (presence: Presence, layout: string) => choose({ frames: { [line.id]: { presence, layout } } });

  // Widening a pick. A layout for the chapter or the film reaches the lines of this presence
  // there, and is asked first when it would redraw more than one picture.
  const scope = line.override?.scope;
  const [wide, setWide] = useState<{ film: boolean; redraws: number } | null>(null);
  useEffect(() => setWide(null), [line.id, line.layout]);
  const applyFor = (film: boolean) => {
    const set = { layouts: { [line.presence]: line.layout } };
    const unset = { layouts: { [line.presence]: null } };
    return choose({
      // the line's own layout, and its chapter's when the film takes over, give way to it
      frames: { [line.id]: { layout: null } },
      chapters: { [chapter.id]: film ? unset : set },
      ...(film ? { all: set } : {}),
    });
  };
  const askFor = (film: boolean) => {
    const redraws = redrawnBy(view, line.presence, line.layout, film ? undefined : chapter.id);
    if (redraws > 1) setWide({ film, redraws });
    else void applyFor(film);
  };
  const undo = () =>
    scope === "film"
      ? choose({ all: { layouts: { [line.presence]: null } } })
      : scope === "chapter"
        ? choose({ chapters: { [chapter.id]: { layouts: { [line.presence]: null } } } })
        : choose({ frames: { [line.id]: { presence: null, layout: null } } });
  const reach = scope ? linesIn(view, line.presence, scope === "chapter" ? chapter.id : undefined).filter((x) => x.line.layout === line.layout).length : 0;

  // The picture this line shows is drawn once, on the line that brings it in: its kind and how
  // it comes in are picked there, whichever of its lines is open.
  const lead = unit ? allLines(view).find((x) => x.line.id === unit.frames[0])?.line : undefined;
  const drawn = unit?.kind === "picture" && lead;
  const others = unit ? unit.frames.filter((id) => id !== line.id) : [];
  const forPicture = () => unit && choose({ frames: Object.fromEntries(unit.frames.map((id) => [id, { presence: line.presence, layout: line.layout }])) });
  const planMove = line.transition && line.transition !== "none" ? line.transition : "cut";
  const move = line.picked?.transition ?? planMove;
  const bringsIn = drawn && lead.id === line.id && line.presence !== "person";
  const shows = line.shows || lead?.shows;

  return (
    <aside className="ep-choices" aria-label="Choices for this line">
      <section>
        <h3>
          Frame <span>{LAYOUTS[line.layout] ?? line.layout}</span>
        </h3>
        <div className="ep-layouts" role="radiogroup" aria-label="The frame for this line">
          {frames.map((k) => (
            <Tooltip key={k.layout} content={`${LAYOUTS[k.layout] ?? k.layout} · ${WHO[k.presence]}`} side="top">
              <button
                type="button"
                role="radio"
                aria-checked={line.layout === k.layout}
                aria-label={`${LAYOUTS[k.layout] ?? k.layout}: ${WHO[k.presence]}`}
                disabled={busy || (presenterOff && k.presence !== "content")}
                onClick={() => line.layout !== k.layout && void setFrame(k.presence, k.layout)}
              >
                <LayoutThumb view={view} layout={k.layout} />
              </button>
            </Tooltip>
          ))}
        </div>
        {presenterOff && <small>Nobody is on screen in this film.</small>}
        {line.override && !wide && (
          <p className="ep-picked" data-rows>
            <span>{scope ? `Set for the ${scope} · ${reach} ${reach === 1 ? "line" : "lines"}` : "Your pick"}</span>
            <button type="button" className="linkish" disabled={busy} onClick={() => void undo()}>
              Undo
            </button>
            {scope !== "film" && (
              <span>
                Use it for{" "}
                {!scope && others.length > 0 && (
                  <>
                    <button type="button" className="linkish" disabled={busy} onClick={() => void forPicture()}>
                      the picture
                    </button>
                    {", "}
                  </>
                )}
                {!scope && (
                  <>
                    <button type="button" className="linkish" disabled={busy} onClick={() => askFor(false)}>
                      the chapter
                    </button>
                    {" or "}
                  </>
                )}
                <button type="button" className="linkish" disabled={busy} onClick={() => askFor(true)}>
                  the film
                </button>
              </span>
            )}
          </p>
        )}
        {wide && (
          <p
            className="ep-confirm"
            role="alertdialog"
            aria-label={`Use ${LAYOUTS[line.layout] ?? line.layout} for the ${wide.film ? "film" : "chapter"}`}
            onKeyDown={(e) => {
              if (e.key !== "Escape") return;
              e.stopPropagation();
              setWide(null);
            }}
          >
            <span>
              {LAYOUTS[line.layout] ?? line.layout} for the {wide.film ? "film" : "chapter"} redraws {wide.redraws} pictures.
            </span>
            <button
              type="button"
              className="btn primary"
              autoFocus
              disabled={busy}
              onClick={() => {
                const film = wide.film;
                setWide(null);
                void applyFor(film);
              }}
            >
              Use it
            </button>
            <button type="button" className="btn" onClick={() => setWide(null)}>
              Cancel
            </button>
          </p>
        )}
      </section>

      <section>
        <h3>
          Picture {unit && <span>{unit.kind === "undesigned" ? "Being planned" : (PICTURES[unit.kind_of_picture] ?? "")}</span>}
        </h3>
        {unit ? (
          <>
            {shows && <p className="ep-shows">{shows}</p>}
            <div className="ep-picture-row">
              <SegmentedControl<Level>
                size="sm"
                value={unit.level}
                disabled={busy || unit.kind === "undesigned"}
                onChange={(level) => level !== unit.level && void choose({ units: { [unit.id]: { level } } })}
                options={[
                  { value: "simple", label: "Simple" },
                  { value: "rich", label: "Rich" },
                ]}
              />
              {unit.kind === "picture" && (
                <button type="button" className="linkish" onClick={onAskPicture}>
                  Ask for a change
                </button>
              )}
            </div>
            <small>
              {unit.kind === "undesigned"
                ? "The writer is planning a picture for this line."
                : unit.level === "rich"
                  ? "Posed as stills for your go before it counts as made."
                  : `Made at once from the plan.${unit.suggest === "rich" ? " Rich is suggested for this one." : ""}`}
            </small>
          </>
        ) : (
          <small>{line.presence === "person" ? "None: this line is said to camera. Pick a frame with a picture to give it one." : "None for this line."}</small>
        )}
      </section>

      {line.cues && line.cues.length > 0 && (
        <details className="ep-more">
          <summary>
            Steps <span>{line.cues.length}</span>
          </summary>
          <ol className="ep-cues">
            {line.cues.map((c, i) => (
              <li key={i}>
                <b>“{c.at}”</b> {c.does}
              </li>
            ))}
          </ol>
        </details>
      )}
      {bringsIn && (
        <details className="ep-more">
          <summary>
            Comes in by <span>{TRANSITIONS[move] ?? "Cut"}</span>
          </summary>
          <span className="ep-looks" role="group" aria-label="How the picture comes in">
            {view.options.transitions.map((id) => (
              <button type="button" key={id} aria-pressed={move === id} disabled={busy} onClick={() => move !== id && void choose({ frames: { [line.id]: { transition: id === planMove ? null : id } } })}>
                {TRANSITIONS[id] ?? id}
              </button>
            ))}
          </span>
          {line.picked?.transition && (
            <p className="ep-picked">
              <span>Your pick</span>
              <button type="button" className="linkish" disabled={busy} onClick={() => void choose({ frames: { [line.id]: { transition: null } } })}>
                Undo
              </button>
            </p>
          )}
        </details>
      )}
      {drawn && unit && (
        <details className="ep-more">
          <summary>
            Kind <span>{PICTURES[unit.kind_of_picture] ?? "Picture"}</span>
          </summary>
          <span className="ep-looks" role="group" aria-label="What kind of picture it is">
            {view.options.pictures.map((id) => (
              <button
                type="button"
                key={id}
                aria-pressed={unit.kind_of_picture === id}
                disabled={busy}
                onClick={() => unit.kind_of_picture !== id && void choose({ frames: { [lead.id]: { picture: id === lead.picture ? null : id } } })}
              >
                {PICTURES[id] ?? id}
              </button>
            ))}
          </span>
          {lead.picked?.picture && (
            <p className="ep-picked">
              <span>Your pick</span>
              <button type="button" className="linkish" disabled={busy} onClick={() => void choose({ frames: { [lead.id]: { picture: null } } })}>
                Undo
              </button>
            </p>
          )}
        </details>
      )}

      <footer>
        <span>
          {LOOKS[theme?.id ?? ""] ?? "Look"} · {view.settings.voice === "narrator" ? "narrator" : "your voice"}
        </span>
        <button type="button" className="linkish" onClick={onFilm}>
          Change
        </button>
      </footer>
    </aside>
  );
}
