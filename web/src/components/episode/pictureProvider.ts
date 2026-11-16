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
