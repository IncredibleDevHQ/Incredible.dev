import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { api, type EpisodeUnit, type EpisodeView, type WriterId } from "../../api";
import { Popover } from "../Popover";
import { Select } from "../Select";
import { TextArea } from "../TextArea";
import type { Run } from "./Ask";

const title = (id: string) => id.replaceAll("-", " ").replace(/^./, (c) => c.toUpperCase());
type Props = { view: EpisodeView; unit: EpisodeUnit; busy: boolean; run: Run };

export function GenerationSettings(props: Props) {
  const { unit, busy } = props;
  const [open, setOpen] = useState(false);
  const used = unit.picture.generation;
  const legacy = !used && !!unit.picture.builder;
  const gen = used ?? unit.generation;
  const priorWriter = props.view.options.picture_writers.find((w) => w.id === unit.picture.builder);
  return (
    <div className="ep-generation">
      <button
        type="button"
        className="linkish"
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={busy}
        onClick={() => setOpen(!open)}
        title="Change provider, model and effort"
      >
        {legacy ? priorWriter?.provider || unit.picture.builder : gen.provider} <ChevronDown size={13} />
      </button>
      <small>{legacy ? "Model and effort unrecorded" : `${gen.model} · ${gen.effort}`}</small>
      {used &&
        (used.provider !== unit.generation.provider ||
          used.model !== unit.generation.model ||
          used.effort !== unit.generation.effort) && (
          <small>
            Next · {unit.generation.provider} · {unit.generation.model} · {unit.generation.effort}
          </small>
        )}
      <Popover open={open} onClose={() => setOpen(false)} title="Picture generation" align="start" width={420}>
        {open && <SettingsForm {...props} close={() => setOpen(false)} />}
      </Popover>
    </div>
  );
}

function SettingsForm({ view, unit, run, busy, close }: Props & { close: () => void }) {
  const [component, setComponent] = useState(unit.visual.automatic ? "" : unit.visual.component);
  const [variant, setVariant] = useState(unit.visual.variant_pick || "");
  const [direction, setDirection] = useState(unit.visual.direction);
  const [providerPick, setProviderPick] = useState<WriterId | "">(unit.builder_pick || "");
  const inherited = view.builders[unit.chapter] || view.writer;
  const writer = providerPick || inherited;
  const [model, setModel] = useState(unit.model_pick.model);
  const [effort, setEffort] = useState(unit.model_pick.effort);
  const options = view.options;
  const models = options.generation_models[writer] ?? [];
  const efforts = models.find((m) => m.id === model)?.efforts ?? [];
  const demoCustom = writer === "demo" && !!direction.trim();
  const save = async (generate: boolean) => {
    const fields = {
      builder: providerPick || null,
      component: component || null,
      variant: variant || null,
      direction: direction.trim(),
      model,
      effort,
    };
    const ok = await run(() => api.chooseEpisode(view.id, { units: { [unit.id]: fields } }));
    if (!ok) return;
    if (generate && !(await run(() => api.makePictures(view.id, { units: [unit.id], level: unit.level })))) return;
    close();
  };
  return (
    <div className="ep-generation-form">
      <Select
        label="Provider"
        value={providerPick}
        options={[
          {
            value: "",
            label: "Use chapter provider (" + (options.picture_writers.find((p) => p.id === inherited)?.provider ?? inherited) + ")",
          },
          ...options.picture_writers.map((w) => ({
            value: w.id,
            label: w.provider,
            description: w.ready ? w.title : w.title + " · unavailable on this host",
            disabled: !w.ready,
          })),
        ]}
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
      <ComponentFields
        unit={unit}
        view={view}
        component={component}
        variant={variant}
        onComponent={(v) => {
          setComponent(v);
          setVariant("");
        }}
        onVariant={setVariant}
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
          {writer === "demo"
            ? "Generate preview"
            : "Generate with " + (options.picture_writers.find((w) => w.id === writer)?.provider ?? writer)}
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
