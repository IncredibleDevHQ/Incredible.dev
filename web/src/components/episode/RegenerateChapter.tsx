import { RotateCcw } from "lucide-react";
import { useRef, useState } from "react";
import { api, type EpisodeView, type WriterId } from "../../api";
import { AgentMark } from "../../ui";
import { Popover } from "../Popover";
import { Select } from "../Select";
import type { Run } from "./Ask";
import { optionLabel } from "./models";
import { writerName } from "./pictureProvider";

type Provider = Exclude<WriterId, "demo">;

export function RegenerateChapter({ view, chapter, count, disabled, run }: {
  view: EpisodeView; chapter: string; count: number; disabled: boolean; run: Run;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState<Provider | "">("");
  const [model, setModel] = useState("");
  const providers = view.options.picture_writers.filter(w => w.id !== "demo");
  const models = view.options.generation_models[provider] ?? [];
  const visuals = `${count} ${count === 1 ? "visual" : "visuals"}`;
  const ready = !disabled && (!provider || providers.some(w => w.id === provider && w.ready) &&
    models.some(m => m.id === model));

  const submit = async () => {
    if (!ready) return;
    const generation = provider ? { provider, model } : undefined;
    if (await run(() => api.regenerateChapter(view.id, chapter, generation))) setOpen(false);
  };

  return (
    <>
      <button ref={trigger} type="button" className="btn" aria-haspopup="dialog" aria-expanded={open}
        disabled={disabled}
        onClick={() => {
          if (!open) {
            setProvider("");
            setModel("");
          }
          setOpen(!open);
        }}>
        <RotateCcw aria-hidden="true" /> Regenerate chapter
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={trigger} align="end" width={340}
        className="ep-edit-picker" title="Regenerate chapter"
        description={`Rebuild ${visuals} from the existing chapter plan.`}>
        <form className="ep-regenerate-form" onSubmit={event => { event.preventDefault(); void submit(); }}>
          <Select label="Provider" value={provider} disabled={disabled}
            options={[
              { value: "", label: "Use existing settings" },
              ...providers.map(w => ({
                value: w.id,
                label: writerName(w.id),
                icon: <AgentMark mark={w.id} size="sm" />,
                description: w.ready ? undefined : "Unavailable on this host",
                disabled: !w.ready,
              })),
            ]}
            onChange={value => {
              setProvider(value as Provider | "");
              setModel(view.options.generation_models[value]?.[0]?.id ?? "");
            }}
          />
          {provider && <Select label="Model" value={model} disabled={disabled || models.length <= 1}
            options={models.map(m => ({ value: m.id, label: optionLabel(m) }))} onChange={setModel} />}
          {provider && <small>Uses this model for every visual in this run.</small>}
          <div className="ep-provider-footer">
            <button type="button" className="btn" onClick={() => setOpen(false)}>Cancel</button>
            <button type="submit" className="btn primary" disabled={!ready}>Regenerate {visuals}</button>
          </div>
        </form>
      </Popover>
    </>
  );
}
