// What a person can choose for the picked line, in the order they would think of it: the frame
// (one pick sets who has it and the layout), then the picture it shows. A pick is the line's
// own until it is widened, in one click, to the picture's other lines, the chapter or the film.
import { api, type EpisodeChapter, type EpisodeChoices, type EpisodeFrame, type EpisodeUnit, type EpisodeView, type Presence } from "../../api";
import { allLines, LAYOUTS, linesIn, LOOKS, MOVES, PICTURES, pictureWords, TRANSITIONS } from "../../episode";
import { Tooltip } from "../Tooltip";
import type { Run } from "./Ask";
import { KindArt, MoveArt } from "./PictureArt";
import { LayoutThumb } from "./Stage";
import { Tiles } from "./Tiles";

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
  // there. Like any pick it draws nothing: the pictures it puts out of date wait to be applied.
  const scope = line.override?.scope;
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
  const askFor = (film: boolean) => void applyFor(film);
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
        {line.override && (
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
      </section>

      <section>
        <h3>
          Picture {unit && <span>{unit.kind === "undesigned" ? "Being planned" : (PICTURES[unit.kind_of_picture] ?? "")}</span>}
        </h3>
        {unit ? (
          <>
            {shows && <p className="ep-shows">{shows}</p>}
            {/* how it is made (simple or rich, and by whom) is set on its block in the script */}
            {unit.kind === "undesigned" ? (
              <small>The writer is planning a picture for this line.</small>
            ) : (
              <div className="ep-picture-row">
                <small>
                  {unit.level === "rich" ? "Rich" : "Simple"} · {pictureWords(unit, view)}
                </small>
                <button type="button" className="linkish" onClick={onAskPicture}>
                  Ask for a change
                </button>
              </div>
            )}
          </>
        ) : (
          <small>{line.presence === "person" ? "None: this line is said to camera. Pick a frame with a picture to give it one." : "None for this line."}</small>
        )}
      </section>

      {drawn && unit && (
        <details className="ep-more">
          <summary>
            Kind <span>{PICTURES[unit.kind_of_picture] ?? "Picture"}</span>
          </summary>
          <Tiles
            label="What kind of picture it is"
            columns={3}
            disabled={busy}
            value={unit.kind_of_picture}
            onPick={(id) => void choose({ frames: { [lead.id]: { picture: id === lead.picture ? null : id } } })}
            options={view.options.pictures.map((k) => ({ value: k.id, label: PICTURES[k.id] ?? k.id, means: k.means, art: <KindArt kind={k.id} /> }))}
          />
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
      {bringsIn && (
        <details className="ep-more">
          <summary>
            Comes in by <span>{TRANSITIONS[move] ?? "Cut"}</span>
          </summary>
          <Tiles
            label="How the picture comes in"
            columns={2}
            disabled={busy}
            value={move}
            onPick={(id) => void choose({ frames: { [line.id]: { transition: id === planMove ? null : id } } })}
            options={view.options.transitions.map((t) => ({
              value: t.id,
              label: TRANSITIONS[t.id] ?? t.id,
              note: t.seconds > 0 ? `${t.seconds} s` : undefined,
              means: MOVES[t.id] ?? "",
              art: <MoveArt move={t.id} />,
            }))}
          />
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
