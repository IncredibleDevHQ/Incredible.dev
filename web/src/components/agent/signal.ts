// Whether an agent's turn is alive, and what it is at between two of its steps, worked out from
// what was last heard from it. An agent that says what its model is doing as it goes (thinking,
// the file it is writing) is heard from every few seconds, so a long silence from it is a worry;
// one that tells only of whole steps says nothing while it thinks, so the same silence is its
// usual way. Nothing here moves on its own: a turn reads as alive only while it is heard from.
// Written for this house from notes on how agent-progress components behave; no other
// component's source is in it.

// What the agent's own stream last said its model is doing, and when: `at` when it was last
// heard from, `since` when it began what it is at, `text` the newest words of its thought or
// the step the call it is writing will be, `amount` the tokens thought or characters written.
export type TrailPulse = { at: number; since: number; doing: "" | "thinking" | "writing" | "step"; text: string; amount: number };

// Seconds an agent may say nothing before the trail says so.
export const QUIET = 20;
// Seconds of silence before a turn may be stuck: from an agent that says what it is doing as it
// goes, and from one that says nothing while it thinks.
export const LOST_TELLING = 90;
export const LOST_SILENT = 600;

// live: heard from just now. quiet: silent, as far as is usual for this agent. lost: silent
// longer than a healthy turn is.
export type Signal = "live" | "quiet" | "lost";

export type Now =
  // the model is thinking: its newest words where the agent gives them, else how much so far
  | { kind: "thinking"; since: number; words: string; tokens: number }
  // it is writing a tool call (`step` is the step it will be) or, with none, its own words
  | { kind: "writing"; since: number; step: string; amount: number }
  // an agent that says what it is doing has said nothing for a while: its model has not answered yet
  | { kind: "waiting"; since: number }
  // an agent that tells only of whole steps, between two of them
  | { kind: "quiet"; since: number }
  // silent longer than a healthy turn is
  | { kind: "lost"; since: number };

// What a turn is at now, or nothing when its newest step says it all. `last` is when its
// newest step or note came (or when the turn began, before it had any).
export function nowOf(now: number, last: number | null, pulse: TrailPulse | null, tells: boolean): Now | null {
  if (last === null) return null;
  // a pulse older than the newest step is about what came before it
  const fresh = pulse && pulse.at >= last ? pulse : null;
  const heard = Math.max(last, fresh?.at ?? 0);
  const silent = now - heard;
  if (silent >= (tells ? LOST_TELLING : LOST_SILENT)) return { kind: "lost", since: heard };
  if (fresh?.doing === "thinking") return { kind: "thinking", since: fresh.since, words: fresh.text, tokens: fresh.amount };
  if (fresh?.doing === "step") return { kind: "writing", since: fresh.since, step: fresh.text, amount: fresh.amount };
  if (fresh?.doing === "writing") return { kind: "writing", since: fresh.since, step: "", amount: fresh.amount };
  if (silent < QUIET) return null;
  return { kind: tells ? "waiting" : "quiet", since: heard };
}

export function signalOf(at: Now | null): Signal {
  if (at === null || at.kind === "thinking" || at.kind === "writing") return "live";
  return at.kind === "lost" ? "lost" : "quiet";
}

// The end of a thought, where the thinking has got to: its last words from a word's start, on
// one line.
export function tail(words: string, max = 150): string {
  const said = words.trim();
  if (said.length <= max) return said;
  const cut = said.slice(said.length - max);
  const from = cut.indexOf(" ");
  return `…${from >= 0 && from < 24 ? cut.slice(from + 1) : cut}`;
}

// A count as it is read: "950", "12,400".
export function counted(n: number): string {
  return Math.max(0, Math.round(n)).toLocaleString("en-US");
}
