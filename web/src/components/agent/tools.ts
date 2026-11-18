// What an agent's step was, read from the words the house gives each tool call ("Reading
// pictures/pic.html", "Searching for “id” in plan.json", `research.describe` on the server): the
// kind of tool, its verb as it is happening and as it was once something came after it, and what
// it acted on. Written for this house from notes on how agent-progress components behave; no other
// component's source is in it.

export type ToolKind = "read" | "write" | "edit" | "search" | "web" | "list" | "run" | "helper" | "plan" | "other";
export type ToolStep = { kind: ToolKind; verb: string; did: string; target: string };

// Longest openings first, so "Searching the web for" is never taken for "Searching for".
const OPENINGS: [string, ToolKind, string][] = [
  ["Searching the web for ", "web", "Searched the web for"],
  ["Searching for ", "search", "Searched for"],
  ["Asking a helper: ", "helper", "Asked a helper"],
  ["Reading ", "read", "Read"],
  ["Writing ", "write", "Wrote"],
  ["Editing ", "edit", "Edited"],
  ["Listing ", "list", "Listed"],
  ["Running ", "run", "Ran"],
  ["Using ", "other", "Used"],
];

export function toolOf(text: string): ToolStep {
  const said = text.trim();
  if (said === "Planning its steps") return { kind: "plan", verb: said, did: "Planned its steps", target: "" };
  for (const [opening, kind, did] of OPENINGS) {
    if (!said.startsWith(opening)) continue;
    const target = said.slice(opening.length).trim();
    const verb = opening.trim().replace(/:$/, "");
    // a page read from the web is the web's, whatever the verb
    return { kind: kind === "read" && /^https?:\/\//.test(target) ? "web" : kind, verb, did, target };
  }
  return { kind: "other", verb: said, did: said, target: "" };
}
