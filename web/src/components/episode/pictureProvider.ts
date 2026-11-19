import type { EpisodeOptions, EpisodeUnit, WriterId } from "../../api";

const writerNames: Record<WriterId, string> = {
  codex: "Codex",
  claude: "Claude",
  kimi: "Kimi",
  demo: "Scripted",
  builtin: "Built-in agent",
};

export function writerName(id: string): string {
  return Object.hasOwn(writerNames, id) ? writerNames[id as WriterId] : id;
}

export function pictureProvider(unit: EpisodeUnit, writers: EpisodeOptions["picture_writers"]): string {
  const picture = unit.picture;
  if (picture.builder) return picture.builder;
  if (picture.generation?.provider) {
    const matches = writers.filter((w) => w.provider === picture.generation?.provider);
    return matches.length === 1 ? matches[0].id : picture.generation.provider;
  }
  return picture.status === "made" || picture.status === "go" ? "Unknown provider" : unit.builder;
}

// A suggestion is applied only when the editor chooses it. Provenance stays on the saved picture.
export function editModel(
  unit: EpisodeUnit,
  writers: EpisodeOptions["picture_writers"],
  models: EpisodeOptions["generation_models"],
): {writer: WriterId | null; model: string; suggested: boolean} {
  if (unit.builder_pick || unit.builder !== "demo") {
    return { writer: unit.builder, model: unit.model_pick.model || "", suggested: false };
  }
  const ready = writers.filter(w => w.ready && w.id !== "demo");
  const writer = (ready.find(w => w.id === "codex") || ready[0])?.id ?? null;
  return { writer, model: writer ? models[writer]?.find(m => m.id)?.id || "" : "", suggested: true };
}

export function editTriggerText(writer: WriterId | null, model?: string): string {
  if (!writer) return "Choose model";
  if (writer === "demo") return "Local preview";
  return model && model !== "CLI default" ? model : writerName(writer);
}
