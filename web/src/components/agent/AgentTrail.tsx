// An agent's work as one quiet trail: its stages in order, the done ones with a check and how
// long each took, the one it is on saying who is at it with a running clock, and under that the
// agent's steps (each tool call with its kind and what it touched) and its own words as they
// come. When the agent says nothing for a while, the trail says it is still at work and for how
// long. A note the person left rests under the stage that took it in. Written for this house
// from notes on how agent-progress components behave; no other component's source is in it.
import {
  Bot,
  Check,
  CornerDownRight,
  FilePen,
  FilePlus,
  FileText,
  FolderOpen,
  Globe,
  Hourglass,
  ListChecks,
  Pause,
  Search,
  SquareTerminal,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Clock, useNow } from "./Clock";
import { middle, took } from "./format";
import { toolOf, type ToolKind } from "./tools";
import "./agent.css";

export type TrailState = "pending" | "running" | "done" | "failed" | "waiting";
export type TrailStage = {
  id: string;
  label: string;
  state: TrailState;
  // seconds since the epoch: a running step counts from its start, a done one with both says
  // how long it took
  startedAt?: number | null;
  endedAt?: number | null;
  // who or what a running step is with, in a word or two ("Claude Code", "Rendering")
  doing?: string;
  // an agent is in a turn on this step: its work shows under it, and its silences are said
  working?: boolean;
  // a quiet word for the step: why a pending one waits, what a failed one says, a waiting one's ask
  word?: string;
  // the person's notes the step took in
  taken?: { id: string; text: string }[];
};
export type TrailEvent = { kind: "step" | "note"; text: string; at: number };

// How many of the newest steps and words show before the older ones fold away.
const SHOWN = 5;
// Seconds the agent may say nothing before the trail says it is still at work.
const QUIET = 20;

const ICONS: Record<ToolKind, typeof FileText> = {
  read: FileText,
  write: FilePlus,
  edit: FilePen,
  search: Search,
  web: Globe,
  list: FolderOpen,
  run: SquareTerminal,
  helper: Bot,
  plan: ListChecks,
  other: Wrench,
};

const SAID: Partial<Record<TrailState, string>> = { done: "done", failed: "stopped", waiting: "needs you" };

export function AgentTrail({
  label,
  steps,
  events = [],
  turnSince = null,
  quietAfter = QUIET,
}: {
  label: string;
  steps: TrailStage[];
  // the agent's current turn: its work so far (tool calls and its own words, oldest first) and
  // when it began, which is where a silence counts from before it has said anything
  events?: TrailEvent[];
  turnSince?: number | null;
  quietAfter?: number;
}) {
  // What a screen reader hears: a step that finishes, stops or waits on the person, said once.
  const [heard, setHeard] = useState("");
  const was = useRef<Record<string, TrailState>>({});
  useEffect(() => {
    const changed = steps.filter((s) => was.current[s.id] !== undefined && was.current[s.id] !== s.state && SAID[s.state]);
    if (changed.length) setHeard(changed.map((s) => `${s.label}: ${SAID[s.state]}`).join(". "));
    was.current = Object.fromEntries(steps.map((s) => [s.id, s.state]));
  }, [steps]);
  const done = steps.filter((s) => s.state === "done").length;

  return (
    <div className="ag-trail">
      <ol aria-label={`${label}, ${done} of ${steps.length} done`}>
        {steps.map((step, i) => {
          const next = steps[i + 1];
          // the line to the next step is the way already covered once that step is reached
          const covered = step.state === "done" && next !== undefined && next.state !== "pending";
          return (
            <li
              key={step.id}
              className="ag-step"
              data-state={step.state}
              data-covered={covered || undefined}
              aria-current={step.state === "running" ? "step" : undefined}
            >
              <div className="ag-row">
                <span className="ag-mark" aria-hidden="true">
                  {step.state === "done" ? <Check /> : step.state === "failed" ? <X /> : step.state === "waiting" ? <Pause /> : null}
                </span>
                <span className="ag-title">{step.label}</span>
                {/* keyed by state, so what it says comes in afresh when the step moves on */}
                <span className="ag-meta" key={step.state}>
                  <Meta step={step} />
                </span>
              </div>
              {step.taken && step.taken.length > 0 && (
                <ul className="ag-taken" aria-label="Your notes it took in">
                  {step.taken.map((note) => (
                    <li key={note.id}>
                      <CornerDownRight aria-hidden="true" />
                      <q>{note.text}</q>
                      <span className="ag-tag">Taken in</span>
                    </li>
                  ))}
                </ul>
              )}
              {step.state === "running" && step.working && (
                <Work events={events} since={turnSince ?? step.startedAt ?? null} quietAfter={quietAfter} who={step.doing ?? ""} />
              )}
            </li>
          );
        })}
      </ol>
      <span className="sr-only" role="status" aria-live="polite">
        {heard}
      </span>
    </div>
  );
}

function Meta({ step }: { step: TrailStage }) {
  switch (step.state) {
    case "running":
      return (
        <>
          {step.doing && <span className="ag-doing">{step.doing}</span>}
          {step.startedAt ? <Clock since={step.startedAt} /> : null}
        </>
      );
    case "done": {
      const time = step.startedAt && step.endedAt ? took(step.endedAt - step.startedAt) : "";
      return time ? <span className="ag-took">{time}</span> : null;
    }
    case "failed":
      return <span className="ag-failed">{step.word || "Stopped"}</span>;
    case "waiting":
      return <span className="ag-badge">{step.word || "Needs you"}</span>;
    default:
      return step.word ? <span className="ag-word">{step.word}</span> : null;
  }
}

// The running step's work: its newest steps and words, the older ones folded away, and, when
// the agent has said nothing for a while, a line that says it is still at it.
function Work({ events, since, quietAfter, who }: { events: TrailEvent[]; since: number | null; quietAfter: number; who: string }) {
  const [all, setAll] = useState(false);
  const folded = all ? 0 : Math.max(0, events.length - SHOWN);
  const shown = events.slice(folded);
  const last = events.length ? events[events.length - 1].at : since;
  const now = useNow(last !== null);
  const quiet = last !== null && now - last >= quietAfter;
  if (!shown.length && !quiet) return null;
  return (
    <div className="ag-work" aria-label={`What ${who || "the agent"} is doing`}>
      {events.length > SHOWN && (
        <button type="button" className="ag-fold" aria-expanded={all} onClick={() => setAll((a) => !a)}>
          {all ? "Show fewer" : `+${folded} earlier`}
        </button>
      )}
      <ol>
        {shown.map((event, n) => (
          <WorkRow key={`${event.at}-${n + folded}`} event={event} latest={!quiet && n === shown.length - 1} />
        ))}
        {quiet && last !== null && (
          <li className="ag-quiet" title="An agent says nothing while it thinks, or while it writes a long file.">
            <Hourglass aria-hidden="true" />
            <span>Still working, nothing new for</span>
            <Clock since={last} />
          </li>
        )}
      </ol>
    </div>
  );
}

function WorkRow({ event, latest }: { event: TrailEvent; latest: boolean }) {
  if (event.kind === "note") {
    // the agent in its own words
    return (
      <li className="ag-say" data-latest={latest || undefined} title={event.text}>
        <q>{event.text}</q>
      </li>
    );
  }
  const tool = toolOf(event.text);
  const Icon = ICONS[tool.kind];
  return (
    <li className="ag-tool" data-kind={tool.kind} data-latest={latest || undefined} title={event.text}>
      <span className="ag-tool-icon" aria-hidden="true">
        <Icon />
      </span>
      <span className="ag-tool-verb">{tool.verb}</span>
      {tool.target && <span className="ag-tool-target">{middle(tool.target)}</span>}
    </li>
  );
}
