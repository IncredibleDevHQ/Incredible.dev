import { useState } from "react";
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
  const used = unit.picture.generation?.provider;
  const inherited = view.builders[unit.chapter] || view.writer;
  return (
    <div className="ep-generation" title={used ? "Last built with " + used : undefined}>
      <Select
        size="sm"
        aria-label="Picture provider"
        disabled={busy}
        value={unit.builder_pick ?? ""}
        options={providers(view, unit).map((p) =>
          p.value
            ? p
            : {
                ...p,
                label: view.options.picture_writers.find((w) => w.id === inherited)?.provider ?? inherited,
                description: "Chapter default",
              },
        )}
        onChange={(id) =>
          void run(() =>
            api.chooseEpisode(view.id, { units: { [unit.id]: { builder: (id as WriterId) || null, model: "", effort: "" } } }),
          )
        }
      />
    </div>
  );
}

export function SettingsForm({ view, unit, run, busy }: Props) {
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
