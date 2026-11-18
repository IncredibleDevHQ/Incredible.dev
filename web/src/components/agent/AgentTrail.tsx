// An agent's work as one quiet trail. Its stages stand on one line: a done one with a check and
// how long it took, the one under way saying what it is doing with its own time, and the ones to
// come. The work of the stage under way branches off the line beside it and rejoins it after: the
// notes the person left that it took in, each step the agent takes as a dot and a word with what
// it touched on the right, its own words, and, when it has said nothing for a while, a line that
// says it is still at it; a light runs down the branch to the newest step. Over the trail, where
// they are given, the agent at work, the whole run's time (which runs on from stage to stage,
// while each stage's starts afresh) and how many stages are done. Written for this house from
// notes on how agent-progress components behave; no other component's source is in it.
import { Check, CornerDownRight, Pause, X } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Clock, useNow } from "./Clock";
import { middle, took } from "./format";
import { toolOf } from "./tools";
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
  // what a running step is doing, in a word or two ("Drawing", "Checking")
  doing?: string;
  // an agent is in a turn on this step: its work branches off under it
  working?: boolean;
  // a quiet word for the step: what a failed one says, a waiting one's ask
  word?: string;
  // under it, in a few words: what a finished step left behind, or what a step to come will do
  detail?: string;
  // the person's notes the step took in
  taken?: { id: string; text: string }[];
};
export type TrailEvent = { kind: "step" | "note"; text: string; at: number };

// How many of the newest steps and words show before the older ones fold away.
const SHOWN = 5;
// Seconds the agent may say nothing before the trail says it is still at work.
const QUIET = 20;

const SAID: Partial<Record<TrailState, string>> = { done: "done", failed: "stopped", waiting: "needs you" };

export function AgentTrail({
  label,
  steps,
  events = [],
  turnSince = null,
  quietAfter = QUIET,
  total = null,
  agent = null,
  count = false,
}: {
  label: string;
  steps: TrailStage[];
  // the agent's current turn: its work so far (tool calls and its own words, oldest first) and
  // when it began, which is where a silence counts from before it has said anything
  events?: TrailEvent[];
  turnSince?: number | null;
  quietAfter?: number;
  // over the trail: the whole run (when it began, and once it is over how long it took), the
  // agent at work, and how many of its stages are done
  total?: { since: number; seconds?: number | null } | null;
  agent?: { name: string; mark?: ReactNode } | null;
  count?: boolean;
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
  // The stage an agent is in a turn on, and when the agent last said anything there.
  const at = steps.find((s) => s.state === "running" && s.working);
  const last = events.length ? events[events.length - 1].at : (turnSince ?? at?.startedAt ?? null);
  const now = useNow(Boolean(at) && last !== null);
  const quiet = Boolean(at) && last !== null && now - last >= quietAfter;

  return (
    <div className="ag-trail">
      {(agent || total || count) && (
        <div className="ag-head">
          {agent && (
            <span className="ag-agent">
              {agent.mark}
              <span>{agent.name}</span>
            </span>
          )}
          <span className="ag-head-end">
            {total && (
              <span className="ag-total" title="The whole run so far">
                {total.seconds != null ? took(total.seconds) : <Clock since={total.since} />}
              </span>
            )}
            {count && (
              <span className="ag-count" aria-label={`${done} of ${steps.length} stages done`}>
                {done}/{steps.length}
              </span>
            )}
          </span>
        </div>
      )}
      <ol aria-label={`${label}, ${done} of ${steps.length} done`}>
        {steps.map((step, i) => {
          const next = steps[i + 1];
          // the line to the next step is the way already covered once that step is reached
          const covered = step.state === "done" && next !== undefined && next.state !== "pending";
          // the stage under way opens onto its work once there is something to show
          const branching = step === at && (events.length > 0 || quiet || Boolean(step.taken?.length));
          return (
            <li
              key={step.id}
              className="ag-step"
              data-state={step.state}
              data-covered={covered || undefined}
              data-branching={branching || undefined}
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
              {step.state !== "running" && step.detail && <p className="ag-detail">{step.detail}</p>}
              {branching ? (
                <Branch events={events} taken={step.taken ?? []} quiet={quiet} since={last} rejoins={Boolean(next)} who={step.doing ?? ""} />
              ) : (
                step.taken && step.taken.length > 0 && <Taken notes={step.taken} />
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

// The person's notes a finished stage took in, under it.
function Taken({ notes }: { notes: { id: string; text: string }[] }) {
  return (
    <ul className="ag-taken" aria-label="Your notes it took in">
      {notes.map((note) => (
        <li key={note.id}>
          <CornerDownRight aria-hidden="true" />
          <q>{note.text}</q>
          <span className="ag-tag">Taken in</span>
        </li>
      ))}
    </ul>
  );
}

// The stage under way's work, off the line beside it: the notes it took in, its newest steps and
// words with the older ones folded away, and a line when the agent has said nothing for a while.
function Branch({
  events,
  taken,
  quiet,
  since,
  rejoins,
  who,
}: {
  events: TrailEvent[];
  taken: { id: string; text: string }[];
  quiet: boolean;
  since: number | null;
  rejoins: boolean;
  who: string;
}) {
  const [unfolded, setUnfolded] = useState(false);
  const folded = unfolded ? 0 : Math.max(0, events.length - SHOWN);
  const shown = events.slice(folded);
  // how far the light runs: from the bend down to the newest step's dot, 24 px a row
  const rows = taken.length + (events.length > SHOWN ? 1 : 0) + shown.length;
  const run = { "--ag-run": `${Math.max(0, (rows - 0.5) * 24 - 28)}px` } as CSSProperties;
  return (
    <div className="ag-branch" data-live={(!quiet && events.length > 0) || undefined} style={run} aria-label={`What ${who ? who.toLowerCase() : "the agent"} is doing`}>
      <svg className="ag-bend" viewBox="0 0 24 12" aria-hidden="true">
        <path d="M9 0 C9 7 21 5 21 12" />
      </svg>
      <ol className="ag-subs">
        {taken.map((note) => (
          <li key={note.id} className="ag-sub" data-kind="taken" title={note.text}>
            <i aria-hidden="true" />
            <q>{note.text}</q>
            <span className="ag-tag">Taken in</span>
          </li>
        ))}
        {events.length > SHOWN && (
          <li className="ag-sub" data-kind="fold">
            <i aria-hidden="true" />
            <button type="button" className="ag-fold" aria-expanded={unfolded} onClick={() => setUnfolded((was) => !was)}>
              {unfolded ? "Show fewer" : `+${folded} earlier`}
            </button>
          </li>
        )}
        {shown.map((event, n) => (
          <Sub key={`${event.at}-${n + folded}`} event={event} latest={!quiet && n === shown.length - 1} />
        ))}
        {quiet && since !== null && (
          <li className="ag-sub" data-kind="quiet" title="An agent says nothing while it thinks, or while it writes a long file.">
            <i aria-hidden="true" />
            <span className="ag-sub-title">
              Still working, nothing new for <Clock since={since} />
            </span>
          </li>
        )}
      </ol>
      <i className="ag-light" aria-hidden="true" />
      {rejoins && (
        <svg className="ag-bend" viewBox="0 0 24 12" aria-hidden="true">
          <path d="M21 0 C21 7 9 5 9 12" />
        </svg>
      )}
    </div>
  );
}

// One step the agent took (a word for the tool and what it touched, on the right), or its own
// words; the newest is the one at work.
function Sub({ event, latest }: { event: TrailEvent; latest: boolean }) {
  if (event.kind === "note") {
    return (
      <li className="ag-sub" data-kind="said" data-latest={latest || undefined} title={event.text}>
        <i aria-hidden="true" />
        <q>{event.text}</q>
      </li>
    );
  }
  const tool = toolOf(event.text);
  return (
    <li className="ag-sub" data-kind={tool.kind} data-latest={latest || undefined} title={event.text}>
      <i aria-hidden="true" />
      {/* what it is doing while it is the newest, what it did once something came after it */}
      <span className="ag-sub-title">{latest ? tool.verb : tool.did}</span>
      {tool.target && <span className="ag-sub-detail">{middle(tool.target, 40)}</span>}
    </li>
  );
}
