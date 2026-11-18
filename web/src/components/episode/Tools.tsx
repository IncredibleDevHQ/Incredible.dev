// The film's own choices, in the bar so they are at hand on every page: how it looks, whose voice
// says it, how its pictures are made, and which agent works on it. Each is free to try: a choice
// that changes how pictures are drawn puts the made ones out of date and runs nothing; the person
// applies their changes when they have settled them. Each button says what is chosen and opens the choice
// under it. A look is shown by the frames it is made of; one that would redraw pictures already
// made asks first. The film, once rendered, is downloaded from the bar too.
import { AudioLines, Bot, ChevronDown, Download, LayoutTemplate, Shapes, Sparkles, TriangleAlert, type LucideIcon } from "lucide-react";
import { useId, useRef, useState, type ReactNode } from "react";
import { api, type EpisodeChoices, type EpisodeUnit, type EpisodeView } from "../../api";
import { keepWriter, LEVEL_NAMES, linesOf, LOOKS, pictureCount, PICTURES, pictureState, voiceName } from "../../episode";
import { Popover } from "../Popover";
import { Tooltip } from "../Tooltip";
import { AgentModel, offersPicks } from "./AgentModel";
import { turning, type Run } from "./Ask";
import { pickLabel } from "./models";
import { WRITERS } from "./Film";
import { againCost } from "./Picture";
import { LayoutThumb } from "./Stage";
import { CloneDialog, NarratorVoice } from "./Voice";

type Props = { view: EpisodeView; run: Run; busy: boolean };

export function FilmTools({ view, run, busy }: Props) {
  return (
    <div className="ep-tools" role="group" aria-label="The film's choices">
      <LookTool view={view} run={run} busy={busy} />
      <VoiceTool view={view} run={run} busy={busy} />
      <PicturesTool view={view} run={run} busy={busy} />
      <AgentTool view={view} run={run} busy={busy} />
    </div>
  );
}

// A button that names a choice and what is chosen, and opens the choice under it.
function Tool({ icon: Icon, label, value, width, children }: { icon: LucideIcon; label: string; value: string; width: number; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={button} type="button" className="ep-tool" aria-haspopup="dialog" aria-expanded={open} aria-label={`${label}: ${value}`} onClick={() => setOpen((o) => !o)}>
        <Icon aria-hidden="true" />
        <span>{label}</span>
        <em>{value}</em>
        <ChevronDown aria-hidden="true" />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={button} side="bottom" align="start" offset={8} width={width} className="ep-tool-pop" title={label}>
        {children(() => setOpen(false))}
      </Popover>
    </>
  );
}

const choose = (view: EpisodeView, run: Run, settings: EpisodeChoices["settings"]) => run(() => api.chooseEpisode(view.id, { settings }));

// The looks the film can wear, each drawn as the frames it is made of: the one it is named for,
// large, and the next ones it uses beside it.
function LookTool({ view, run, busy }: Props) {
  const presenterOff = view.settings.presenter === "off";
  const looks = view.options.themes.filter((t) => (t.presenter === "off") === presenterOff);
  const now = view.options.themes.find((t) => t.id === view.settings.theme);
  const made = asked(view);
  return (
    <Tool icon={LayoutTemplate} label="Look" value={LOOKS[view.settings.theme] ?? now?.name ?? "None"} width={520}>
      {() => (
        <>
          <div className="ep-look-cards">
            {looks.map((t) => {
              const [usual] = t.kit;
              return (
                <button
                  key={t.id}
                  type="button"
                  className="ep-look-card"
                  aria-pressed={view.settings.theme === t.id}
                  disabled={busy}
                  onClick={() => t.id !== view.settings.theme && void choose(view, run, { theme: t.id })}
                >
                  {usual && <LayoutThumb view={view} layout={usual.layout} />}
                  <b>{LOOKS[t.id] ?? t.name}</b>
                  <small>{t.stage}</small>
                </button>
              );
            })}
          </div>

          {made > 0 && <Untouched />}
        </>
      )}
    </Tool>
  );
}

// Pictures asked for already: a pick puts them out of date, and nothing more until it is applied.
const asked = (view: EpisodeView) => {
  const pictures = pictureCount(view);
  return pictures.all - pictures.planned;
};

// Said under a choice that changes how pictures are drawn, once some are made.
function Untouched() {
  return <p className="ep-tool-note">Try any of them: pictures already made are drawn again only when you apply your changes.</p>;
}

// Whose voice says the film: the person's own takes, or a narrator for the lines nobody recorded.
function VoiceTool({ view, run, busy }: Props) {
  const presenterOff = view.settings.presenter === "off";
  const narrator = view.options.narrator.ready;
  const voice = view.settings.voice;
  const clone = view.settings.cloned_voice;
  const usingClone = voice === "narrator" && !!clone && clone.id === view.settings.narrator?.id;
  const [upload, setUpload] = useState(false);
  const value = voiceName(view.settings);
  return (
    <>
      <Tool icon={AudioLines} label="Voice" value={value} width={380}>
        {(close) => (
          <>
            <Options
              label="Voice"
              value={usingClone ? "clone" : voice}
              disabled={busy}
              onChange={(v) => {
                if (v === "clone") {
                  if (clone) void choose(view, run, { voice: "narrator", narrator: clone });
                  else { close(); setUpload(true); }
                } else {
                  const reset = v === "narrator" && clone && clone.id === view.settings.narrator?.id;
                  void choose(view, run, { voice: v, ...(reset ? { narrator: null } : {}) });
                }
              }}
              options={[
                { value: "live", label: presenterOff ? "Recorded" : "Your voice", note: "You record each chapter; your takes are the film's sound." },
                ...(view.options.local_narrator
                  ? [{ value: "local" as const, label: "Local narrator", note: "An installed synthetic voice reads the script offline." }]
                  : []),
                {
                  value: "narrator",
                  label: "ElevenLabs",
                  note: narrator ? "Choose a voice to narrate unrecorded lines." : "Set ELEVENLABS_API_KEY on the Studio host and restart to enable.",
                  disabled: !narrator,
                },
                { value: "clone", label: "Cloned voice", note: clone ? clone.name : narrator ? "Record or upload a voice sample." : "Set up ElevenLabs to add a voice sample.", disabled: !narrator },
              ]}
            />
            {usingClone && (
              <button
                className="linkish"
                type="button"
                disabled={!narrator || busy}
                onClick={() => {
                  close();
                  setUpload(true);
                }}
              >
                Replace cloned voice
              </button>
            )}
            {usingClone && clone?.verify && <small>Verify this voice in ElevenLabs before using it for narration.</small>}
            {voice === "narrator" && !usingClone && narrator && <NarratorVoice view={view} run={run} busy={busy} />}
          </>
        )}
      </Tool>
      {upload && <CloneDialog view={view} run={run} onDone={() => setUpload(false)} />}
    </>
  );
}

// How the film's pictures are made, where a picture has no level of its own: at once from the
// plan, or as motion graphics, each line planned as a shot, with a still of each line for a go. Free to try: a picture already made
// at the other level is out of date until the person applies their changes.
function PicturesTool({ view, run, busy }: Props) {
  const level = view.settings.level;
  return (
    <Tool icon={Shapes} label="Pictures" value={LEVEL_NAMES[level]} width={380}>
      {() => (
        <>
          <Options
            label="Pictures"
            value={level}
            disabled={busy}
            onChange={(next) => void choose(view, run, { level: next })}
            options={[
              { value: "simple", label: LEVEL_NAMES.simple, note: "Drawn at once from the plan." },
              { value: "rich", label: LEVEL_NAMES.rich, note: "Each line planned as a shot, then drawn. You check a still of each line before your go." },
            ]}
          />
          {asked(view) > 0 && <Untouched />}
        </>
      )}
    </Tool>
  );
}

// What a person's picks and changes wait on, run when they say so: nothing is planned or drawn
// while they try frames, looks and levels out. It says what will run (the writer's part, the
// pictures drawn again, the new ones) and, since drawing a made picture again redoes paid work,
// what that costs, before anything starts.
export function ApplyChanges({ view, run, busy }: Props) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const pictures = view.units.filter((u) => u.kind === "picture");
  const again = pictures.filter((u) => pictureState(u, view) === "changed");
  const fresh = view.approved ? pictures.filter((u) => u.picture.status === "none") : [];
  const lines = view.waiting.length;
  const writer = WRITERS[view.settings.writer] ?? "The writer";
  const Writer = writer.slice(0, 1).toUpperCase() + writer.slice(1);
  const waits = (kind: string) => view.waiting.filter((w) => w.kind === kind).length;
  // what the writer does first, said for each kind of change that waits on it
  const writes = [
    [waits("pick"), "plans a picture for the line you gave one", "plans pictures for the N lines you gave one"],
    [waits("added"), "designs the picture for the line you added", "designs the pictures for the N lines you added"],
    [waits("words"), "fits a picture's steps to the words you changed", "fits pictures' steps to the words you changed in N lines"],
  ] as const;
  const count = lines + again.length + fresh.length;
  const redrawOnly = again.length > 0 && count === again.length;
  const redrawLabel = `Redraw ${again.length} ${again.length === 1 ? "visual" : "visuals"}`;
  if (count === 0) return null;
  return (
    <>
      <button ref={button} type="button" className="btn primary ep-apply" aria-haspopup="dialog" aria-expanded={open} disabled={turning(view)} onClick={() => setOpen((o) => !o)}>
        {redrawOnly ? redrawLabel : <>Apply changes <b>{count}</b></>}
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchor={button}
        side="bottom"
        align="end"
        offset={8}
        width={420}
        className="ep-apply-pop"
        title={redrawOnly ? "Review out-of-date visuals" : "Apply your changes"}
        description={redrawOnly ? undefined : "Review the pending work before applying."}
      >
        {!redrawOnly && <ul className="ep-apply-list">
          {writes.map(
            ([n, one, many]) =>
              n > 0 && (
                <li key={one}>
                  <Bot aria-hidden="true" />
                  <span>
                    <b>
                      {Writer} {n === 1 ? one : many.replace("N", String(n))}
                    </b>
                    , first.
                  </span>
                </li>
              ),
          )}
          {fresh.length > 0 && (
            <li>
              <Sparkles aria-hidden="true" />
              <span>
                <b>
                  {fresh.length} new {fresh.length === 1 ? "picture is" : "pictures are"} made
                </b>
                .
              </span>
            </li>
          )}
        </ul>}
        {open && again.length > 0 && <RedrawList view={view} units={again} />}
        {again.length > 0 && (
          <p className="ep-apply-warn" role="note">
            <TriangleAlert aria-hidden="true" />
            <span>{againCost(again)}</span>
          </p>
        )}
        <div className="ep-apply-act">
          <button type="button" className="btn" onClick={() => setOpen(false)}>
            Not now
          </button>
          <button
            type="button"
            className="btn primary"
            autoFocus
            disabled={busy || turning(view)}
            onClick={() => {
              setOpen(false);
              void run(() => api.applyEpisode(view.id));
            }}
          >
            {redrawOnly ? redrawLabel : "Apply changes"}
          </button>
        </div>
      </Popover>
    </>
  );
}

function RedrawList({ view, units }: { view: EpisodeView; units: EpisodeUnit[] }) {
  const groups = (view.plan?.chapters ?? []).map((chapter, index) => ({
    title: `Chapter ${index + 1} · ${chapter.question}`,
    lines: linesOf(chapter),
    units: units.filter(unit => unit.chapter === chapter.id),
  }));
  const chapterIds = new Set(view.plan?.chapters.map(chapter => chapter.id));
  const other = units.filter(unit => !chapterIds.has(unit.chapter));
  if (other.length) groups.push({ title: "Other visuals", lines: [], units: other });
  return (
    <div className="ep-redraw-list" role="region" aria-label="Out-of-date visuals by chapter" tabIndex={0}>
      {groups.filter(group => group.units.length).map(group => (
        <section role="group" aria-label={group.title} key={group.title}>
          <h4>{group.title}</h4>
          <ul>{group.units.map(unit => {
            const first = group.lines.findIndex(line => unit.frames.includes(line.id));
            return <li key={unit.id}>
              <b>{PICTURES[unit.kind_of_picture] ?? "Visual"}{first >= 0 && ` · Beat ${first + 1}`}</b>
              <span>{unit.shows || group.lines[first]?.vo}</span>
            </li>;
          })}</ul>
        </section>
      ))}
    </div>
  );
}

// The film's agent: it writes the changes asked for and draws the pictures, from here on. Shown
// where more than one is ready on this computer. A chapter can have another draw its pictures.
function AgentTool({ view, run, busy }: Props) {
  const ready = view.options.writers.filter((w) => w.ready);
  const now = view.options.writers.find((w) => w.id === view.settings.writer);
  const models = view.options.generation_models[view.settings.writer] ?? [];
  const pick = { model: view.settings.writer_model ?? "", effort: view.settings.writer_effort ?? "" };
  const picks = offersPicks(models);
  if (ready.length < 2 && !picks) return null;
  // the bar names what the film's agent runs on, where that is picked or the agent says it
  const on = pickLabel(models, pick);
  return (
    <Tool icon={Bot} label="Agent" value={[now?.title ?? "None", on].filter(Boolean).join(" · ")} width={380}>
      {(close) => (
        <>
          {ready.length > 1 && (
            <Options
              label="Agent"
              value={view.settings.writer}
              disabled={busy || turning(view)}
              onChange={(writer) => {
                close();
                keepWriter(writer);
                void choose(view, run, { writer });
              }}
              options={ready.map((w) => ({
                value: w.id,
                label: w.title,
                note: w.local ? "A coding agent on this computer, signed in as you are." : "The engine's own agent, on the model it is set up with.",
              }))}
            />
          )}
          {picks && (
            <div className="ep-agent-pick">
              <AgentModel models={models} pick={pick} disabled={busy || turning(view)} onChange={(next) => void choose(view, run, { writer_model: next.model, writer_effort: next.effort })} />
              <small>What {now?.title ?? "the agent"} runs on for this film: the changes you ask for, and every picture without a pick of its own.</small>
            </div>
          )}
        </>
      )}
    </Tool>
  );
}

// One of a few, each said in a line: the arrow keys move between them, as radio buttons do.
function Options<T extends string>({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; note: string; disabled?: boolean }[];
  disabled: boolean;
  onChange: (value: T) => void;
}) {
  const name = useId();
  return (
    <fieldset className="ep-options">
      <legend className="sr-only">{label}</legend>
      {options.map((o) => (
        <label key={o.value} data-disabled={o.disabled || undefined}>
          <input type="radio" name={name} value={o.value} checked={o.value === value} disabled={disabled || o.disabled} onChange={() => o.value !== value && onChange(o.value)} />
          <span>
            <b>{o.label}</b>
            <small>{o.note}</small>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

// The rendered film, as a file: the last render, said so when the film has changed since.
export function FilmDownload({ view }: { view: EpisodeView }) {
  const film = view.film_state;
  if (film.status !== "done" || !film.file) return null;
  return (
    <Tooltip content={film.stale ? "Download the film as last rendered; it has changed since" : "Download the film"} side="bottom" align="end">
      <a className="icon-btn" href={film.file.url} download={`${view.title}.mp4`} aria-label="Download the film">
        <Download />
      </a>
    </Tooltip>
  );
}
