// What an agent's step was, read from the words the house gives each tool call ("Reading
// pictures/pic.html", "Searching for “id” in plan.json", `research.describe` on the server): the
// kind of tool, its verb, and what it acted on. Written for this house from notes on how
// agent-progress components behave; no other component's source is in it.

export type ToolKind = "read" | "write" | "edit" | "search" | "web" | "list" | "run" | "helper" | "plan" | "other";
export type ToolStep = { kind: ToolKind; verb: string; target: string };

// Longest openings first, so "Searching the web for" is never taken for "Searching for".
const OPENINGS: [string, ToolKind][] = [
  ["Searching the web for ", "web"],
  ["Searching for ", "search"],
  ["Asking a helper: ", "helper"],
  ["Reading ", "read"],
  ["Writing ", "write"],
  ["Editing ", "edit"],
  ["Listing ", "list"],
  ["Running ", "run"],
  ["Using ", "other"],
];

export function toolOf(text: string): ToolStep {
  const said = text.trim();
  if (said === "Planning its steps") return { kind: "plan", verb: said, target: "" };
  for (const [opening, kind] of OPENINGS) {
    if (!said.startsWith(opening)) continue;
    const target = said.slice(opening.length).trim();
    const verb = opening.trim().replace(/:$/, "");
    // a page read from the web is the web's, whatever the verb
    return { kind: kind === "read" && /^https?:\/\//.test(target) ? "web" : kind, verb, target };
  }
  return { kind: "other", verb: said, target: "" };
}
