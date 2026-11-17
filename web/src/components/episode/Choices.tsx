// What a person can choose for the line open in the frame, one panel at a time, picked from the
// rail at the frame's right edge the way the Figma editor's pop-up has it: the layout (one pick
// sets who has the frame and how), the picture the line shows, how that picture comes in, and
// the steps it takes on the line. A pick is the line's own until it is widened, in one click, to
// the picture's other lines, the chapter or the film; like every pick it draws nothing.
import { portraits, portraitUrl } from "./portraits";
import { BackgroundSettings } from "./BackgroundSettings";
import { Palette, Settings2, Blend, LayoutTemplate, ListOrdered, Shapes, type LucideIcon } from "lucide-react";
import { api, type EpisodeChapter, type EpisodeChoices, type EpisodeFrame, type EpisodeUnit, type EpisodeView, type Presence } from "../../api";
import { allLines, LAYOUTS, LEVEL_NAMES, linesIn, LOOKS, MOVES, PICTURES, pictureWords, TRANSITIONS } from "../../episode";
import { ComponentFields, SettingsForm } from "./GenerationSettings";
import { Tooltip } from "../Tooltip";
import type { Run } from "./Ask";
import { KindArt, MoveArt } from "./PictureArt";
import { LayoutThumb } from "./Stage";
import { Tiles } from "./Tiles";

const WHO: Record<Presence, string> = { person: "You", both: "You and the picture", content: "The picture alone" };
const ORDER: Record<Presence, number> = { person: 0, both: 1, content: 2 };

export type Panel = "layout" | "picture" | "transition" | "steps" | "background" | "others";
export const PANELS: { id: Panel; label: string; icon: LucideIcon }[] = [
  { id: "layout", label: "Layout", icon: LayoutTemplate },
  { id: "picture", label: "Picture", icon: Shapes },
  { id: "transition", label: "Transition", icon: Blend },
  { id: "steps", label: "Steps", icon: ListOrdered },
  { id: "background", label: "Cover", icon: Palette },
  { id: "others", label: "Others", icon: Settings2 },
];

type Props = {
  view: EpisodeView;
  chapter: EpisodeChapter;
  line: EpisodeFrame;
  unit?: EpisodeUnit;
  run: Run;
  busy: boolean;
  onFilm: () => void;
  onAskPicture: () => void;
  draftSize: number | null;
  onDraftSize: (value: number | null) => void;
};

export function ChoicePanel({ panel, ...props }: Props & { panel: Panel }) {
  const panels = { layout: LayoutPanel, picture: PicturePanel, transition: TransitionPanel, steps: StepsPanel, background: BackgroundSettings, others: OtherSettings };
  const Selected = panels[panel];
  return (
    <div className="ep-choices" data-panel={panel} aria-label={`${PANELS.find((p) => p.id === panel)?.label} for this line`}>
      <Selected key={panel === "background" ? JSON.stringify([props.view.settings.background_color, props.view.settings.background_texture]) : panel} {...props} />
    </div>
  );
}

function OtherSettings({ view, unit, busy, run }: Props) {
  if (unit?.kind !== "picture") return <small>This line has no generated picture.</small>;
  const revision = [unit.id, unit.builder_pick, unit.builder, unit.model_pick.model, unit.model_pick.effort, unit.visual.direction];
  return <SettingsForm key={revision.join("/")} view={view} unit={unit} busy={busy} run={run} />;
}

const choosing = (view: EpisodeView, run: Run) => (body: EpisodeChoices) => run(() => api.chooseEpisode(view.id, body));

// The look's layouts, you first, then you with a picture, then the picture alone; one pick sets
// who has the frame and how. The line's own layout is always among them, even one the look no
// longer has.
function LayoutPanel({ view, chapter, line, unit, run, busy, onFilm, draftSize, onDraftSize }: Props) {
  const presenterOff = view.settings.presenter === "off";
  const theme = view.options.themes.find((t) => t.id === view.settings.theme);
  const choose = choosing(view, run);
  const kit = [...(theme?.kit ?? [])].sort((a, b) => ORDER[a.presence] - ORDER[b.presence]);
  const frames = kit.some((k) => k.layout === line.layout) ? kit : [{ layout: line.layout, presence: line.presence }, ...kit];
  const setFrame = (presence: Presence, layout: string) => choose({ frames: { [line.id]: { presence, layout } } });

  const size = line.picked?.window_size;
  const savedSize = typeof size === "number" ? size : size === "small" ? 72 : size === "large" ? 125 : 100;
  const commitSize = async () => {
    if (draftSize === null || busy) return;
    if (draftSize !== savedSize) await choose({frames: {[line.id]: {window_size: draftSize === 100 ? null : draftSize}}});
    onDraftSize(null);
  };

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
  const undo = () =>
    scope === "film"
      ? choose({ all: { layouts: { [line.presence]: null } } })
      : scope === "chapter"
        ? choose({ chapters: { [chapter.id]: { layouts: { [line.presence]: null } } } })
        : choose({ frames: { [line.id]: { presence: null, layout: null } } });
  const reach = scope ? linesIn(view, line.presence, scope === "chapter" ? chapter.id : undefined).filter((x) => x.line.layout === line.layout).length : 0;
  const others = unit ? unit.frames.filter((id) => id !== line.id) : [];
  const forPicture = () => unit && choose({ frames: Object.fromEntries(unit.frames.map((id) => [id, { presence: line.presence, layout: line.layout }])) });

  return (
    <>
      <h3>
        Layout <span>{LAYOUTS[line.layout] ?? line.layout}</span>
      </h3>
      <div className="ep-layouts" role="radiogroup" aria-label="The frame for this line">
        {frames.map((k) => (
          <Tooltip key={k.layout} content={`${LAYOUTS[k.layout] ?? k.layout} · ${WHO[k.presence]}`} side="left">
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
      {!presenterOff && line.presence !== "content" && <div className="ep-window-fields">
        <label className="ep-size-range">
          <span>Video box size <output>{draftSize ?? savedSize}%</output></span>
          <input type="range" aria-label="Video box size" min={25} max={125} step={1}
            value={draftSize ?? savedSize} disabled={busy}
            onChange={e => onDraftSize(Number(e.target.value))}
            onPointerUp={commitSize} onPointerCancel={() => onDraftSize(null)}
            onKeyUp={commitSize} onBlur={commitSize} />
        </label>
        <fieldset className="ep-window-group">
          <legend>Video box shape</legend>
          <Tiles label="Video box shape" columns={2} disabled={busy} value={line.picked?.window_shape ?? ""}
            options={[
              {value: "", label: "Layout default", art: <LayoutThumb view={view} layout={line.layout} />},
              ...["rectangle", "rounded", "circle"].map(shape => ({
                value: shape, label: shape[0].toUpperCase() + shape.slice(1),
                art: <span className="ep-shape-art" data-shape={shape}><i /></span>,
              })),
            ]}
            onPick={shape => void choose({frames: {[line.id]: {window_shape: shape || null}}})} />
        </fieldset>
        <PortraitPicker selected={view.settings.portrait ?? "mira"} disabled={busy}
          onPick={portrait => void choose({settings: {portrait}})} />
      </div>}
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
                  <button type="button" className="linkish" disabled={busy} onClick={() => void applyFor(false)}>
                    the chapter
                  </button>
                  {" or "}
                </>
              )}
              <button type="button" className="linkish" disabled={busy} onClick={() => void applyFor(true)}>
                the film
              </button>
            </span>
          )}
        </p>
      )}
      <footer>
        <span>
          {LOOKS[theme?.id ?? ""] ?? "Look"} · {view.settings.voice === "local" ? "local narrator" : view.settings.voice === "narrator" ? "narrator" : "your voice"}
        </span>
        <button type="button" className="linkish" onClick={onFilm}>
          Change
        </button>
      </footer>
    </>
  );
}

function PortraitPicker({selected, disabled, onPick}: {selected: string; disabled: boolean; onPick: (portrait: string) => void}) {
  return (
    <fieldset className="ep-window-group ep-portraits">
      <legend>Episode presenter portrait</legend>
      <div className="ep-portrait-pair">
        {portraits.map(name => (
          <button type="button" className="ep-tile" key={name} aria-pressed={selected === name.toLowerCase()}
            disabled={disabled} onClick={() => onPick(name.toLowerCase())}>
            <img src={portraitUrl(name)} alt="" /><span className="ep-tile-name">{name}</span>
          </button>
        ))}
      </div>
    </fieldset>
  );
}

// The picture this line shows: what it shows and where it stands, and its kind, picked on the line
// that brings it in (whichever of its lines is open).
function PicturePanel({ view, line, unit, run, busy, onAskPicture }: Props) {
  const choose = choosing(view, run);
  const lead = unit ? allLines(view).find((x) => x.line.id === unit.frames[0])?.line : undefined;
  const drawn = unit?.kind === "picture" && lead;
  const shows = line.shows || lead?.shows;
  return (
    <>
      <div className="ep-picture-options">
        <h3>Picture {unit && <span>{unit.kind === "undesigned" ? "Being planned" : (PICTURES[unit.kind_of_picture] ?? "")}</span>}</h3>
        {!unit ? (
          <small>{line.presence === "person" ? "None: this line is said to camera. Pick a layout with a picture to give it one." : "None for this line."}</small>
        ) : (
          <>
            {shows && <p className="ep-shows">{shows}</p>}
            {unit.kind === "undesigned" && <small>The writer plans a picture for this line when you apply your changes.</small>}
          </>
        )}
        {drawn && unit && (
          <>
            <ComponentFields unit={unit} view={view} disabled={busy}
              component={unit.visual.automatic ? "" : unit.visual.component} variant={unit.visual.variant_pick || ""}
              onComponent={(v) => void choose({units:{[unit.id]:{component:v || null,variant:null}}})}
              onVariant={(v) => void choose({units:{[unit.id]:{variant:v || null}}})} />
            <h3>
              Kind <span>{PICTURES[unit.kind_of_picture] ?? "Picture"}</span>
            </h3>
            <Tiles
              label="What kind of picture it is"
              columns={2}
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
          </>
        )}
      </div>
      {unit && unit.kind !== "undesigned" && (
        <footer className="ep-picture-status">
          <small>{LEVEL_NAMES[unit.level]} · {pictureWords(unit, view)}</small>
          <button type="button" className="linkish" onClick={onAskPicture}>Ask for a change</button>
        </footer>
      )}
    </>
  );
}

// How the picture comes in, on the line that brings it in. A line said to camera, or one that
// holds the picture before, has nothing coming in.
function TransitionPanel({ view, line, unit, run, busy }: Props) {
  const choose = choosing(view, run);
  const lead = unit ? allLines(view).find((x) => x.line.id === unit.frames[0])?.line : undefined;
  const bringsIn = unit?.kind === "picture" && lead?.id === line.id && line.presence !== "person";
  const planMove = line.transition && line.transition !== "none" ? line.transition : "cut";
  const move = line.picked?.transition ?? planMove;
  return (
    <>
      <h3>Transition {bringsIn && <span>{TRANSITIONS[move] ?? "Cut"}</span>}</h3>
      {!bringsIn ? (
        <small>{line.presence === "person" ? "This line is said to camera: no picture comes in on it." : "Its picture came in on an earlier line: it stays on this one."}</small>
      ) : (
        <>
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
        </>
      )}
    </>
  );
}

// What the picture does on this line, step by step, each on the word it lands on.
function StepsPanel({ line }: Props) {
  const cues = line.cues ?? [];
  return (
    <>
      <h3>Steps {cues.length > 0 && <span>{cues.length}</span>}</h3>
      {cues.length === 0 ? (
        <small>Nothing moves on this line.</small>
      ) : (
        <ol className="ep-cues">
          {cues.map((c, i) => (
            <li key={i}>
              <b>“{c.at}”</b> {c.does}
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
