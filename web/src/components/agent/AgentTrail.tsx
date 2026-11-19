// An agent's work as one quiet trail. Its stages stand on one line: a done one with a check and
// how long it took, the one under way saying what it is doing with its own time, and the ones to
// come. The work of the stage under way branches off the line beside it and rejoins it after: the
// notes the person left that it took in, each step the agent takes as a dot and a word with what
// it touched on the right, its own words, each long stretch of thinking with how long it took,
// and last what its model is at now, between two steps: thinking (with the newest words of the
// thought, or how much so far), the file it is writing and how much of it, or that it has gone
// quiet. Nothing in the trail moves on its own. The mark of the stage under way turns, and the
// newest line beats, only while the agent is heard from; a silence is said as one, and one too
// long for a healthy turn says so in amber with the way to stop it (`signal.ts`). Over the
// trail, where they are given, the agent at work, the whole run's time (which runs on from stage
// to stage, while each stage's starts afresh) and how many stages are done. Written for this
// house from notes on how agent-progress components behave; no other component's source is in
// it.
import { Check, CornerDownRight, Pause, X } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Clock, useNow } from "./Clock";
import { middle, took } from "./format";
import { counted, nowOf, signalOf, tail, type Now, type TrailPulse } from "./signal";
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
// A step the agent took, its own words, or a stretch of thinking that ended (`seconds` long,
// `text` its summary where the agent gives one).
export type TrailEvent = { kind: "step" | "note" | "thought"; text: string; at: number; seconds?: number };

// How many of the newest steps and words show before the older ones fold away.
const SHOWN = 5;

const SAID: Partial<Record<TrailState, string>> = { done: "done", failed: "stopped", waiting: "needs you" };

export function AgentTrail({
  label,
  steps,
  events = [],
  turnSince = null,
  pulse = null,
  tells = false,
  onStop,
  total = null,
  agent = null,
  count = false,
}: {
  label: string;
  steps: TrailStage[];
  // the agent's current turn: its work so far (tool calls, its own words and its thinking,
  // oldest first) and when it began, which is where a silence counts from before it has said
  // anything
  events?: TrailEvent[];
  turnSince?: number | null;
  // what its model is doing between two steps, as the agent's own stream says it, and whether
  // this agent says so at all: one that does and goes silent may be stuck far sooner
  pulse?: TrailPulse | null;
  tells?: boolean;
  // how the person stops a turn that has gone silent
  onStop?: () => void;
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
  // The stage an agent is in a turn on, when its newest step came, and what it is at since.
  const at = steps.find((s) => s.state === "running" && s.working);
  const last = events.length ? events[events.length - 1].at : (turnSince ?? at?.startedAt ?? null);
  const now = useNow(Boolean(at) && last !== null);
  const doing = at ? nowOf(now, last, pulse, tells) : null;
  const signal = signalOf(doing);
  // said once to a screen reader as a turn goes silent for too long
  const lost = Boolean(at) && signal === "lost";
  useEffect(() => {
    if (lost) setHeard(`${label}: no sign of life, it may be stuck`);
  }, [lost, label]);

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
          const branching = step === at && (events.length > 0 || doing !== null || Boolean(step.taken?.length));
          return (
            <li
              key={step.id}
              className="ag-step"
              data-state={step.state}
              data-covered={covered || undefined}
              data-branching={branching || undefined}
              // its mark turns only while the agent is heard from
              data-signal={step === at ? signal : undefined}
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
                <Branch
                  events={events}
                  taken={step.taken ?? []}
                  doing={doing}
                  beat={pulse?.at ?? 0}
                  rejoins={Boolean(next)}
                  who={step.doing ?? ""}
                  agent={agent?.name ?? ""}
                  tells={tells}
                  onStop={onStop}
                />
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

// The stage under way's work, off the line beside it: the notes it took in, its newest steps,
// words and thoughts with the older ones folded away, and last what its model is at now.
function Branch({
  events,
  taken,
  doing,
  beat,
  rejoins,
  who,
  agent,
  tells,
  onStop,
}: {
  events: TrailEvent[];
  taken: { id: string; text: string }[];
  doing: Now | null;
  // when the agent was last heard from: the newest line's dot beats once for each
  beat: number;
  rejoins: boolean;
  who: string;
  agent: string;
  tells: boolean;
  onStop?: () => void;
}) {
  const [unfolded, setUnfolded] = useState(false);
  const folded = unfolded ? 0 : Math.max(0, events.length - SHOWN);
  const shown = events.slice(folded);
  const signal = signalOf(doing);
  // how far the light runs: from the bend down to the newest step's dot, 24 px a row
  const rows = taken.length + (events.length > SHOWN ? 1 : 0) + shown.length;
  const run = { "--ag-run": `${Math.max(0, (rows - 0.5) * 24 - 28)}px` } as CSSProperties;
  return (
    <div className="ag-branch" data-live={(signal === "live" && doing === null && events.length > 0) || undefined} style={run} aria-label={`What ${who ? who.toLowerCase() : "the agent"} is doing`}>
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
          <Sub key={`${event.at}-${n + folded}`} event={event} latest={doing === null && n === shown.length - 1} />
        ))}
        {doing && <NowRow doing={doing} beat={beat} agent={agent} tells={tells} onStop={onStop} />}
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

// What the model is at now, between two steps. Thinking and writing are heard as they go: the
// dot beats once each time the agent is heard from, so a still dot is a silent agent.
function NowRow({ doing, beat, agent, tells, onStop }: { doing: Now; beat: number; agent: string; tells: boolean; onStop?: () => void }) {
  if (doing.kind === "thinking") {
    const words = tail(doing.words);
    return (
      <li className="ag-sub" data-kind="now" data-now="thinking">
        <i key={beat} aria-hidden="true" />
        <span className="ag-sub-title">
          Thinking <Clock since={doing.since} />
        </span>
        {!words && doing.tokens > 0 && <span className="ag-sub-detail">about {counted(doing.tokens)} tokens so far</span>}
        {words && (
          <q className="ag-thought" title={doing.words}>
            {words}
          </q>
        )}
      </li>
    );
  }
  if (doing.kind === "writing") {
    const tool = doing.step ? toolOf(doing.step) : null;
    const much = doing.amount > 0 ? `${counted(doing.amount)} characters` : "";
    return (
      <li className="ag-sub" data-kind="now" data-now="writing" title={doing.step || undefined}>
        <i key={beat} aria-hidden="true" />
        <span className="ag-sub-title">{tool ? tool.verb : "Writing its reply"}</span>
        <span className="ag-sub-detail">{[tool?.target ? middle(tool.target, 32) : "", much].filter(Boolean).join(" · ")}</span>
      </li>
    );
  }
  if (doing.kind === "waiting") {
    return (
      <li className="ag-sub" data-kind="now" data-now="waiting" title="The request is with the model. Its answer has not started.">
        <i aria-hidden="true" />
        <span className="ag-sub-title">
          Waiting for the model <Clock since={doing.since} />
        </span>
      </li>
    );
  }
  const name = agent || "This agent";
  if (doing.kind === "quiet") {
    return (
      <li className="ag-sub" data-kind="now" data-now="quiet">
        <i aria-hidden="true" />
        <span className="ag-sub-title">
          Quiet for <Clock since={doing.since} />
        </span>
        <span className="ag-now-note">{name} reports each step once it is done, and nothing while it thinks.</span>
      </li>
    );
  }
  return (
    <li className="ag-sub" data-kind="now" data-now="lost">
      <i aria-hidden="true" />
      <span className="ag-sub-title">
        No sign of life for <Clock since={doing.since} />
      </span>
      <span className="ag-now-note">
        {tells ? `${name} is usually heard from every few seconds, so it may be stuck.` : `That is longer than a step usually takes ${name}, so it may be stuck.`}
        {onStop && (
          <button type="button" className="ag-stop" onClick={onStop}>
            Stop it
          </button>
        )}
      </span>
    </li>
  );
}

// One step the agent took (a word for the tool and what it touched, on the right), its own
// words, or a stretch of thinking that ended (how long, and where it got to); the newest is
// the one at work.
function Sub({ event, latest }: { event: TrailEvent; latest: boolean }) {
  if (event.kind === "thought") {
    return (
      <li className="ag-sub" data-kind="thought" title={event.text || undefined}>
        <i aria-hidden="true" />
        <span className="ag-sub-title">{event.seconds ? `Thought for ${took(event.seconds)}` : "Thought"}</span>
        {event.text && <span className="ag-sub-detail">{tail(event.text, 64)}</span>}
      </li>
    );
  }
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
