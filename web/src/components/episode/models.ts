// What an agent runs on, in the words the studio uses for it: its models by name, the efforts
// each one takes, and what a picture was made on.
import type { EpisodeUnit, EpisodeView, ModelOption, PictureGeneration } from "../../api";

const EFFORTS: Record<string, string> = { none: "None", minimal: "Minimal", low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Max" };
export const effortName = (effort: string): string => EFFORTS[effort] ?? (effort ? effort[0].toUpperCase() + effort.slice(1) : "");

// What the agent's own default is called where nothing says which model that is.
const UNNAMED = "CLI default";

// A model as its picker lists it. The first row is the agent's own default, and says which model
// that is where the agent tells.
export function optionLabel(option: ModelOption): string {
  if (option.id) return option.name;
  if (option.resolves) return `Default · ${option.resolves}`;
  return option.name === UNNAMED ? "Agent's default" : option.name;
}

export function modelChoices(models: ModelOption[], selected: string, film?: { model: string; effort: string } | null) {
  const defaultOption = models.find(m => !m.id);
  const inherited = film?.model || defaultOption?.resolves || defaultOption?.name;
  const duplicate = defaultOption && (
    models.find(m => m.id && m.id === inherited) ?? models.find(m => m.id && m.name === inherited)
  );
  const pinned = duplicate?.id === selected;
  let defaultLabel = defaultOption ? optionLabel(defaultOption) : "";
  if (film) defaultLabel = `Film's choice · ${pickLabel(models, film) || "its default"}`;
  if (pinned) defaultLabel = film ? "Use film's choice" : "Use default";
  return models.filter(m => m !== duplicate || pinned).map(m => ({
    value: m.id,
    label: m.id ? optionLabel(m) : defaultLabel,
  }));
}

// What a pick comes to, in a few words ("K3.1 Pro · High"): the model by name, then the effort
// picked or, where the agent says it, the one it thinks at by default. Empty when nothing is
// picked and the agent does not say what its default is.
export function pickLabel(models: ModelOption[] | undefined, pick: { model: string; effort: string }): string {
  const option = models?.find((m) => m.id === pick.model);
  const name = !option ? pick.model : option.id ? option.name : (option.resolves ?? (option.name === UNNAMED ? "" : option.name));
  const effort = pick.effort || option?.default_effort || "";
  return [name, effortName(effort)].filter(Boolean).join(" · ");
}

// What a picture being made is built on by `builder`: the beat's model and effort now. The
// scripted builder runs on no model, so it names none.
export function builtOn(view: EpisodeView, unit: EpisodeUnit, builder: string): string {
  return builder === "demo" ? "" : pickLabel(view.options.generation_models[builder], unit.model_now ?? unit.model_pick);
}

// What a made picture's record says it was made on: the model by name, then the effort. A record
// that only says "the agent's default" says nothing here.
export function madeOn(generation: PictureGeneration | null | undefined): string {
  if (!generation) return "";
  const said = (value: string) => (value && value !== UNNAMED && value !== "Not applicable" ? value : "");
  const model = generation.model === "demo" ? "Scripted" : said(generation.model);
  return [model, effortName(said(generation.effort))].filter(Boolean).join(" · ");
}
