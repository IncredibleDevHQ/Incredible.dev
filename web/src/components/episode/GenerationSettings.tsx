import { ChevronDown, Sparkles } from "lucide-react";
import { Popover } from "../Popover";
import { editModel, editTriggerText, pictureProvider, writerName } from "./pictureProvider";
import { useRef, useState } from "react";
import { api, type EpisodeUnit, type EpisodeView, type WriterId } from "../../api";
import { Select } from "../Select";
import { TextArea } from "../TextArea";
import type { Run } from "./Ask";

const title = (id: string) => id.replaceAll("-", " ").replace(/^./, (c) => c.toUpperCase());
type Props = { view: EpisodeView; unit: EpisodeUnit; busy: boolean; run: Run };

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
  const caption = editTriggerText(edit.writer, modelName);
  const details = edit.writer && edit.writer !== "demo" && caption !== writerName(edit.writer)
    ? `${writerName(edit.writer)} · ${caption}` : caption;
  const accessibleLabel = `${edit.suggested && edit.writer ? "Suggested edit model" : "Edit model"}: ${details}`;
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [writer, setWriter] = useState<WriterId | null>(null);
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const models = writer ? availableModels[writer] ?? [] : [];
  const efforts = models.find(m => m.id === model)?.efforts ?? [];
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
        api.chooseEpisode(view.id, { units: { [unit.id]: { builder, model: builder ? model : "", effort: builder ? effort : "" } } }),
      )
    )
      setOpen(false);
  };
  return (
    <div className="ep-generation">
      <button
        ref={trigger}
        type="button"
        className="btn ep-provider-trigger"
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
        <span>{caption}</span><ChevronDown aria-hidden="true" />
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchor={trigger}
        side="bottom"
        align="start"
        width={272}
        className="ep-edit-picker"
        title="Beat edit model"
      >
        <Select
          size="sm" label="Provider" value={writer} placeholder="Choose provider"
          options={writers.map(w => ({
            value: w.id,
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
              size="sm" label="Model" value={model} disabled={!ready || models.length <= 1}
              options={models.map(m => ({value: m.id, label: m.name}))}
              onChange={v => { setModel(v); setEffort(""); }}
            />
            <Select
              size="sm" label="Effort" value={effort} disabled={!ready || !efforts.length}
              options={[
                {value: "", label: efforts.length ? "Default" : "Automatic"},
                ...efforts.map(e => ({value: e, label: title(e)})),
              ]}
              onChange={setEffort}
            />
          </div>
        )}
        {unit.picture.generation && (
          <p className="ep-provider-used">
            Last picture · {used === "demo" ? "Local preview" :
              [writerName(used), unit.picture.generation.model, unit.picture.generation.effort].join(" · ")}
          </p>
        )}
        <div className="ep-provider-footer">
          {unit.builder_pick && (
            <button className="linkish" type="button" disabled={busy} onClick={() => void save(null)}>
              Use chapter default
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
  const efforts = models.find((m) => m.id === model)?.efforts ?? [];
  const demoCustom = writer === "demo" && !!direction.trim();
  const save = async (generate: boolean) => {
    const fields = {
      builder: providerPick || null,
      direction: direction.trim(),
      model,
      effort,
    };
    const ok = await run(() => api.chooseEpisode(view.id, { units: { [unit.id]: fields } }));
    if (!ok) return;
    if (generate) await run(() => api.makePictures(view.id, { units: [unit.id], level: unit.level }));
  };
  return (
    <div className="ep-generation-form">
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
        disabled={models.length <= 1}
        options={models.map((m) => ({ value: m.id, label: m.name }))}
        onChange={(v) => {
          setModel(v);
          setEffort("");
        }}
      />
      <Select
        label="Effort"
        value={effort}
        disabled={!efforts.length}
        options={[
          { value: "", label: writer === "demo" ? "Not applicable" : "Provider default" },
          ...efforts.map((e) => ({ value: e, label: title(e) })),
        ]}
        onChange={setEffort}
      />
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
