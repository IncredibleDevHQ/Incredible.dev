// What making a made picture again costs, said before it is done: another full run of its
// agent, so its tokens are spent again.
import type { EpisodeUnit, Level } from "../../api";
import { WRITERS } from "./Film";

export function againCost(units: Pick<EpisodeUnit, "builder" | "level">[]): string {
  const names = [...new Set(units.map((u) => WRITERS[u.builder] ?? u.builder))];
  const rich = units.some((u) => u.level === "rich");
  const who = names.length === 1 ? names[0] : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  return `${units.length === 1 ? "It is" : "Each is"} another full run of ${who}${rich ? ", and motion graphics plan each shot first" : ""}, so the tokens are spent again.`;
}

// What making a made picture another way asks of the person, said under the stages its builder
// goes through: what comes back to them (a still of each line to check, or nothing), and another
// full run of its builder.
export function levelCost(unit: Pick<EpisodeUnit, "builder">, to: Level): string {
  const builder = WRITERS[unit.builder] ?? unit.builder;
  return to === "rich"
    ? `You play it and check a still of each line before your go puts it in the film. Another full run of ${builder}, so the tokens are spent again.`
    : `No shots to plan and no stills to check: it goes straight into the film. Another full run of ${builder}, so the tokens are spent again.`;
}
