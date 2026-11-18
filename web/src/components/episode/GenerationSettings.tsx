import { ChevronDown, Sparkles } from "lucide-react";
import { Popover } from "../Popover";
import { editModel, editTriggerText, pictureProvider, writerName } from "./pictureProvider";
import { useId, useRef, useState } from "react";
import { api, type EpisodeUnit, type EpisodeView, type ModelOption, type WriterId } from "../../api";
import { effortName, modelChoices, pickLabel } from "./models";
import { AgentMark } from "../../ui";
import { Select } from "../Select";
import { TextArea } from "../TextArea";
import type { Run } from "./Ask";

const title = (id: string) => id.replaceAll("-", " ").replace(/^./, (c) => c.toUpperCase());
type Props = { view: EpisodeView; unit: EpisodeUnit; busy: boolean; run: Run };

// How hard the model thinks, among the levels this model takes. The first stop is its default,
// named where the agent says what that is (`usual`).
export function EffortSlider({ efforts, value, onChange, disabled, automatic = "Automatic", usual }: {
  efforts: string[]; value: string; onChange: (value: string) => void; disabled?: boolean; automatic?: string; usual?: string;
}) {
  const ticks = useId();
  const index = Math.max(0, efforts.indexOf(value) + 1);
  const level = efforts[index - 1];
  const label = level ? effortName(level) : efforts.length ? (usual ? `Default · ${effortName(usual)}` : "Default") : automatic;
  return (
    <label className="ep-size-range ep-effort">
      <span>Effort <output>{label}</output></span>
      {efforts.length > 0 && <>
        <input type="range" aria-label="Effort" aria-valuetext={label} list={ticks}
          min={0} max={efforts.length} step={1} value={index} disabled={disabled}
          onChange={e => onChange(e.currentTarget.valueAsNumber === 0 ? "" : efforts[e.currentTarget.valueAsNumber - 1])} />
        <datalist id={ticks}>
          <option value={0}>Default</option>
          {efforts.map((effort, i) => <option key={effort} value={i + 1}>{title(effort)}</option>)}
        </datalist>
      </>}
    </label>
  );
}

// What a beat that picks nothing of its own is built on: the film's model and effort, while the
// film's agent builds it.
function filmChoice(view: EpisodeView, writer: string | null): { model: string; effort: string } | null {
  const chosen = view.settings;
  if (!writer || writer !== chosen.writer || !(chosen.writer_model || chosen.writer_effort)) return null;
  return { model: chosen.writer_model ?? "", effort: chosen.writer_effort ?? "" };
}

// The row whose efforts hold for a pick: the model picked, else the film's, else the agent's own.
const effortRow = (models: ModelOption[], model: string, film: { model: string; effort: string } | null) =>
  models.find((m) => m.id === (model || film?.model || ""));

function providers(view: EpisodeView, unit: EpisodeUnit) {
  const inherited = view.builders[unit.chapter] || view.writer;
  return [
    { value: "", label: "Chapter default", description: view.options.picture_writers.find((w) => w.id === inherited)?.provider },
    ...view.options.picture_writers.map((w) => ({
      value: w.id,
      label: w.provider,
      description: w.ready ? w.title : w.title + " · unavailable on this host",
      disabled: !w.ready,
    })),
  ];
}

export function GenerationSettings({ view, unit, busy, run }: Props) {
  const writers = view.options.picture_writers;
  const used = pictureProvider(unit, writers);
  const edit = editModel(unit, writers, view.options.generation_models);
  const availableModels = view.options.generation_models;
  const modelName = edit.writer ? availableModels[edit.writer]?.find(m => m.id === edit.model)?.name : undefined;
  const now = unit.model_now ?? { ...unit.model_pick, from: "" };
  // what the beat is built on now: its own pick, else the film's, else the agent's default
  const caption = !edit.suggested && edit.writer && edit.writer !== "demo"
    ? pickLabel(availableModels[edit.writer], now) || writerName(edit.writer)
    : editTriggerText(edit.writer, modelName);
  const details = edit.writer && edit.writer !== "demo" && caption !== writerName(edit.writer)
    ? `${writerName(edit.writer)} · ${caption}` : caption;
  const accessibleLabel = `${edit.suggested && edit.writer ? "Suggested edit model" : "Edit model"}: ${details}`;
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [writer, setWriter] = useState<WriterId | null>(null);
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const models = writer ? availableModels[writer] ?? [] : [];
  const film = filmChoice(view, writer);
  const choices = modelChoices(models, model, film);
  const row = effortRow(models, model, film);
  const efforts = row?.efforts ?? [];
  const ready = writers.some(w => w.id === writer && w.ready);
  const inspect = (writer: WriterId | null) => {
    setWriter(writer);
    if (!writer) return;
    const saved = writer === unit.builder ? unit.model_pick : undefined;
    const made = writer === used ? unit.picture.generation : undefined;
    const models = view.options.generation_models[writer] ?? [];
    const initial = models.find((m) => m.id === (writer === edit.writer ? edit.model : saved?.model || made?.model));
    setModel(initial?.id ?? "");
    const level = saved ? saved.effort : made?.effort || "";
    setEffort(initial?.efforts.includes(level) ? level : "");
  };
  const save = async (builder: WriterId | null) => {
    if (
      await run(() =>
        // an effort picked over the film's choice keeps the film's model, as its own pick
        api.chooseEpisode(view.id, { units: { [unit.id]: { builder, model: builder ? model || (effort ? film?.model ?? "" : "") : "", effort: builder ? effort : "" } } }),
      )
    )
      setOpen(false);
  };
  return (
    <div className="ep-generation">
      <button
        ref={trigger}
        type="button"
        className="btn ep-beat-trigger"
        aria-label={accessibleLabel}
        title={accessibleLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          if (!open) inspect(edit.writer);
          setOpen(!open);
        }}
      >
        {edit.suggested && edit.writer && <Sparkles aria-hidden="true" />}
        {!edit.suggested && edit.writer && edit.writer !== "demo" && <AgentMark mark={edit.writer} size="sm" />}
        <span>{caption}</span><ChevronDown aria-hidden="true" />
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchor={trigger}
        side="bottom"
        align="start"
        width={312}
        className="ep-edit-picker"
        title="Beat edit model"
      >
        <Select
          size="sm" label="Provider" value={writer} placeholder="Choose provider"
          options={writers.map(w => ({
            value: w.id,
            icon: <AgentMark mark={w.id} size="sm" />,
            label: w.id === "demo" ? "Local preview" : writerName(w.id),
            description: !w.ready ? "Unavailable on this host" :
              edit.suggested && w.id === edit.writer ? "Suggested for this beat" : undefined,
            disabled: !w.ready,
          }))}
          onChange={v => inspect(v as WriterId)}
        />
        {writer && writer !== "demo" && (
          <div className="ep-provider-fields">
            <Select
              size="sm" label="Model" value={model} disabled={!ready || choices.length <= 1}
              options={choices}
              onChange={v => { setModel(v); setEffort(""); }}
            />
            <EffortSlider efforts={efforts} value={effort} onChange={setEffort} disabled={!ready}
              usual={(!model && film?.effort) || row?.default_effort} />
          </div>
        )}
        <div className="ep-provider-footer">
          {(unit.builder_pick || now.from === "beat") && (
            <button className="linkish" type="button" disabled={busy} onClick={() => void save(null)}>
              {film ? "Use the film's choice" : "Use chapter default"}
            </button>
          )}
          <button type="button" className="btn primary" disabled={busy || !ready} onClick={() => void save(writer)}>
            Use for beat
          </button>
        </div>
      </Popover>
    </div>
  );
}

export function SettingsForm({ view, unit, run, busy }: Props) {
  const [direction, setDirection] = useState(unit.visual.direction);
  const edit = editModel(unit, view.options.picture_writers, view.options.generation_models);
  const [providerPick, setProviderPick] = useState<WriterId | "">(unit.builder_pick || (edit.suggested && edit.writer) || "");
  const inherited = view.builders[unit.chapter] || view.writer;
  const writer = providerPick || inherited;
  const [model, setModel] = useState(edit.model);
  const [effort, setEffort] = useState(unit.model_pick.effort);
  const options = view.options;
  const models = options.generation_models[writer] ?? [];
  const film = filmChoice(view, writer);
  const choices = modelChoices(models, model, film);
  const row = effortRow(models, model, film);
  const efforts = row?.efforts ?? [];
  const demoCustom = writer === "demo" && !!direction.trim();
  const save = async (generate: boolean) => {
    const fields = {
      builder: providerPick || null,
      direction: direction.trim(),
      // an effort picked over the film's choice keeps the film's model, as its own pick
      model: model || (effort ? film?.model ?? "" : ""),
      effort,
    };
    const ok = await run(() => api.chooseEpisode(view.id, { units: { [unit.id]: fields } }));
    if (!ok) return;
    if (generate) await run(() => api.makePictures(view.id, { units: [unit.id], level: unit.level }));
  };
  return (
    <div className="ep-generation-form">
      <header><b>Picture generation</b><p>Save the drawing instructions for this beat, or generate a new picture with them now.</p></header>
      <Select
        label="Provider"
        value={providerPick}
        options={providers(view, unit)}
        onChange={(v) => {
          setProviderPick(v as WriterId | "");
          setModel("");
          setEffort("");
        }}
      />
      <Select
        label="Model"
        value={model}
        disabled={choices.length <= 1}
        options={choices}
        onChange={(v) => {
          setModel(v);
          setEffort("");
        }}
      />
      <EffortSlider efforts={efforts} value={effort} onChange={setEffort}
        automatic={writer === "demo" ? "Not applicable" : "Provider default"}
        usual={(!model && film?.effort) || row?.default_effort} />
      <TextArea
        label="Custom visual direction"
        minRows={2}
        maxRows={5}
        maxLength={1600}
        value={direction}
        onChange={(e) => setDirection(e.target.value)}
        placeholder="Describe what should appear and how it should move."
      />
      {writer !== "demo" && <small>Generating runs this provider for the picture and uses its tokens.</small>}
      {demoCustom && <small>Select a live provider to generate from your description.</small>}
      <div className="ep-generation-actions">
        <button type="button" className="btn" disabled={busy} onClick={() => void save(false)}>
          Save
        </button>
        <button type="button" className="btn primary" disabled={busy || demoCustom} onClick={() => void save(true)}>
          {writer === "demo" ? "Generate preview" : "Generate picture"}
        </button>
      </div>
    </div>
  );
}

export function ComponentFields({
  unit,
  view,
  component,
  variant,
  onComponent,
  onVariant,
  disabled,
}: Pick<Props, "unit" | "view"> & {
  component: string;
  variant: string;
  onComponent: (v: string) => void;
  onVariant: (v: string) => void;
  disabled?: boolean;
}) {
  const available = unit.visual.options;
  const options = view.options;
  return (
    <>
      <Select
        disabled={disabled}
        label="Component"
        value={component}
        options={[
          { value: "", label: "Automatic (" + title(unit.visual.suggested) + ")" },
          ...Object.keys(available).map((k) => ({
            value: k,
            label: title(k),
            description: options.components[k]?.purpose,
          })),
        ]}
        onChange={onComponent}
      />
      <Select
        disabled={disabled}
        label="Component layout"
        value={variant}
        options={[
          { value: "", label: "Automatic" },
          ...(available[component || unit.visual.suggested] ?? []).map((v) => ({ value: v, label: title(v) })),
        ]}
        onChange={onVariant}
      />
    </>
  );
}
