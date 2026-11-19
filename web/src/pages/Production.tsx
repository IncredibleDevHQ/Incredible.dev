// The production board: every episode's jobs in one place, in the order work moves. On the left,
// what is written and not made yet, by episode and chapter. Beside it the agents: a job, a chapter
// or a whole episode is handed to one by dragging it onto its row (or with the row's number key,
// or from the job's own details), and the row says what that comes to before it is let go; under
// each agent, what it is running and what waits its turn. Then what waits on the person (a go on
// stills, a plan to read, a job that stopped), and what is done. A job unfolds in place to say
// what it is and what can be done about it, opens its episode as a peek over the board (Escape
// comes back), and links to its place in the episode's own page. The board is narrowed to an
// episode, one of its chapters, or an agent, and its address says so.
//
// Written for this house from notes on how boards for handing work to agents, and inboxes of what
// agents need, behave; no other component's source is in it.
import { ChevronRight, Play, RotateCcw, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { api, type ProductionAgent, type ProductionEpisode, type ProductionJob, type ProductionView } from "../api";
import { Clock, useNow } from "../components/agent/Clock";
import { took } from "../components/agent/format";
import { nowOf, tail, type Now } from "../components/agent/signal";
import { toolOf } from "../components/agent/tools";
import { offersPicks, type ModelPick } from "../components/episode/AgentModel";
import { effortName, madeOn, optionLabel, pickLabel } from "../components/episode/models";
import { Select } from "../components/Select";
import { beatsSaid, DOING, LEVEL_NAMES, PICTURES } from "../episode";
import { handOverWords, jobAddress, jobPlace, kept, laneOf, loadOf, pileOf, queueOf, type Pile } from "../production";
import { useHouse } from "../store";
import { AgentMark } from "../ui";
import "./production.css";

// A job by name: the kind of picture and the beats it plays over, or the script.
const jobName = (job: ProductionJob) => (job.what === "script" ? "The script" : [PICTURES[job.kind] ?? "Picture", beatsSaid(job.beats)].filter(Boolean).join(" · "));
const many = (n: number) => `${n} ${n === 1 ? "picture" : "pictures"}`;
// How many waiting jobs an agent's row shows before the rest fold into a count.
const WAITING_SHOWN = 4;

// What is being handed over: the jobs, and what they are called together.
type Carry = { jobs: ProductionJob[]; label: string };

export function Production() {
  const view = useHouse((s) => s.production);
  const filter = useHouse((s) => s.board);
  const setBoard = useHouse((s) => s.setBoard);
  const load = useHouse((s) => s.loadProduction);
  const say = useHouse((s) => s.say);
  const [open, setOpen] = useState<string | null>(null);
  // the model and effort each agent's next jobs run on, picked on its row
  const [picks, setPicks] = useState<Record<string, ModelPick>>({});
  const [busy, setBusy] = useState(false);
  // said once to a screen reader: what a hand-over did
  const [told, setTold] = useState("");

  const hand = useCallback(
    async (jobs: ProductionJob[], agentId: string) => {
      const board = useHouse.getState().production;
      const agent = board?.agents.find((a) => a.id === agentId);
      if (!board || jobs.length === 0) return;
      if (agentId && !agent?.ready) return say(`${agent?.title ?? "That agent"} isn't set up on this computer.`);
      const pick = picks[agentId] ?? { model: "", effort: "" };
      setBusy(true);
      try {
        const done = await api.handOver({ jobs: jobs.map((j) => ({ episode: j.episode, unit: j.unit })), agent: agentId, model: pick.model, effort: pick.effort, start: true });
        const refused = done.refused.map((r) => `${board.episodes.find((e) => e.id === r.episode)?.title ?? "An episode"}: ${r.reason}`);
        const started = done.started.length ? `${many(done.started.length)} ${agent ? `handed to ${agent.title}` : "started"}.` : "";
        const words = [started, ...refused].filter(Boolean).join(" ") || "Nothing was started.";
        setTold(words);
        say(words);
        await load();
      } catch (error) {
        say((error as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [picks, say, load],
  );
  const carrying = useHandOver(hand, busy);

  if (!view) {
    return (
      <section className="page pb-page" aria-labelledby="pb-title">
        <h1 id="pb-title">Production</h1>
        <p className="muted" role="status">
          Reading every episode…
        </p>
      </section>
    );
  }
  const jobs = kept(view.jobs, filter);
  const pile = pileOf(jobs, view.episodes);
  const needs = jobs.filter((j) => laneOf(j) === "needs");
  const done = jobs.filter((j) => laneOf(j) === "done").sort((a, b) => (b.ended_at ?? 0) - (a.ended_at ?? 0));
  const ready = view.agents.filter((a) => a.ready);
  const toMake = pile.reduce((n, g) => n + g.jobs.length, 0);
  const picked = view.episodes.find((e) => e.id === filter.episode);
  const card = (job: ProductionJob, extra?: Partial<JobCardProps>) => (
    <JobCard key={job.id} job={job} view={view} open={open === job.id} onOpen={() => setOpen(open === job.id ? null : job.id)} hand={hand} busy={busy} picks={picks} {...extra} />
  );
  return (
    <section className="page pb-page" aria-labelledby="pb-title" data-carrying={carrying.carry ? "" : undefined}>
      <header className="pb-head">
        <div>
          <h1 id="pb-title">Production</h1>
          <p className="lede">Hand what is written to an agent, watch what runs, and see what waits on you, across every episode.</p>
        </div>
        <div className="pb-filters" role="group" aria-label="Narrow the board">
          <Select
            size="sm"
            aria-label="Episode"
            value={filter.episode}
            options={[{ value: "", label: "All episodes" }, ...view.episodes.map((e) => ({ value: e.id, label: e.title, description: `#${e.channel}` }))]}
            onChange={(episode) => setBoard({ episode })}
          />
          <Select
            size="sm"
            aria-label="Chapter"
            value={filter.chapter}
            disabled={!picked || picked.chapters.length === 0}
            options={[{ value: "", label: "All chapters" }, ...(picked?.chapters ?? []).map((c) => ({ value: c.id, label: `Chapter ${c.n}`, description: c.question }))]}
            onChange={(chapter) => setBoard({ chapter })}
          />
          <Select
            size="sm"
            aria-label="Agent"
            value={filter.agent}
            options={[{ value: "", label: "All agents" }, ...view.agents.map((a) => ({ value: a.id, label: a.title }))]}
            onChange={(agent) => setBoard({ agent })}
          />
        </div>
      </header>
      {view.episodes.length === 0 ? (
        <p className="muted">No episodes yet. Start one from a channel's canvas: once its plan is approved, its pictures show here.</p>
      ) : (
        <div className="pb-lanes">
          <Lane name="To make" count={toMake} hint={ready.length ? `Drag onto an agent, or press 1–${Math.min(9, ready.length)}` : undefined}>
            {pile.length === 0 ? <p className="pb-none">Everything written is made or on its way.</p> : <PileList pile={pile} card={card} carrying={carrying} agents={ready} hand={hand} busy={busy} />}
          </Lane>
          <Lane name="Agents" count={jobs.filter((j) => laneOf(j) === "agents").length} label="Running and waiting">
            <ul className="pb-agents">
              {view.agents.map((agent) => (
                <AgentRow
                  key={agent.id}
                  agent={agent}
                  n={ready.indexOf(agent) + 1}
                  queue={queueOf(jobs, agent.id)}
                  over={carrying.over === agent.id}
                  carry={carrying.carry}
                  pick={picks[agent.id] ?? { model: "", effort: "" }}
                  onPick={(pick) => setPicks((was) => ({ ...was, [agent.id]: pick }))}
                  card={card}
                />
              ))}
            </ul>
          </Lane>
          <Lane name="Needs you" count={needs.length} tone="amber">
            {needs.length === 0 ? <p className="pb-none">Nothing waits on you.</p> : needs.map((j) => card(j, { carrying: j.state === "failed" && j.what === "picture" ? carrying : undefined }))}
          </Lane>
          <Lane name="Done" count={done.length}>
            {done.length === 0 ? <p className="pb-none">Nothing is made yet.</p> : done.map((j) => card(j))}
          </Lane>
        </div>
      )}
      {carrying.carry && carrying.pointer && (
        <div className="pb-ghost" ref={carrying.ghost} aria-hidden="true">
          {carrying.carry.label}
        </div>
      )}
      <span className="sr-only" role="status" aria-live="polite">
        {told}
      </span>
    </section>
  );
}

// Handing work over by hand: a press that moves becomes a carry, the agent's row under it is the
// one it would go to, and letting go there hands it over. Letting go anywhere else changes
// nothing.
type Carrying = ReturnType<typeof useHandOver>;
function useHandOver(hand: (jobs: ProductionJob[], agent: string) => Promise<void>, busy: boolean) {
  const [carry, setCarry] = useState<Carry | null>(null);
  const [into, setInto] = useState<string | null>(null);
  const [pointer, setPointer] = useState(false);
  const ghost = useRef<HTMLDivElement | null>(null);
  const press = useRef<{ x: number; y: number; carry: Carry; moved: boolean } | null>(null);
  const at = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const target = useRef<string | null>(null);
  // a press that became a carry is not also a click on what was pressed
  const carried = useRef(false);
  const handed = useRef(hand);
  handed.current = hand;

  const place = useCallback((node: HTMLDivElement | null) => {
    ghost.current = node;
    if (node) node.style.transform = `translate(${at.current.x + 14}px, ${at.current.y + 12}px)`;
  }, []);
  const end = useCallback(() => {
    press.current = null;
    target.current = null;
    setCarry(null);
    setInto(null);
    setPointer(false);
  }, []);
  useEffect(() => {
    const move = (e: PointerEvent) => {
      const p = press.current;
      if (!p) return;
      at.current = { x: e.clientX, y: e.clientY };
      if (!p.moved) {
        if (Math.hypot(e.clientX - p.x, e.clientY - p.y) < 5) return;
        p.moved = true;
        carried.current = true;
        setCarry(p.carry);
        setPointer(true);
      }
      if (ghost.current) ghost.current.style.transform = `translate(${e.clientX + 14}px, ${e.clientY + 12}px)`;
      const row = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-agent]");
      const agent = row && row.dataset.ready !== undefined ? (row.dataset.agent ?? null) : null;
      if (agent !== target.current) {
        target.current = agent;
        setInto(agent);
      }
    };
    const up = () => {
      const p = press.current;
      const agent = target.current;
      end();
      if (p?.moved && agent) void handed.current(p.carry.jobs, agent);
      // the click that follows this release is the carry's, not a press on the card
      window.setTimeout(() => (carried.current = false), 0);
    };
    const key = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape" && press.current?.moved) {
        e.stopPropagation();
        end();
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", end);
    window.addEventListener("keydown", key, true);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", end);
      window.removeEventListener("keydown", key, true);
    };
  }, [end]);

  return {
    carry,
    over: into,
    pointer,
    ghost: place,
    wasCarried: () => carried.current,
    // what a thing that can be handed over puts on itself
    grip: (jobs: ProductionJob[], label: string) => ({
      onPointerDown: (e: ReactPointerEvent) => {
        if (e.button !== 0 || busy || jobs.length === 0) return;
        at.current = { x: e.clientX, y: e.clientY };
        press.current = { x: e.clientX, y: e.clientY, carry: { jobs, label }, moved: false };
      },
    }),
  };
}

function Lane({ name, count, label, hint, tone, children }: { name: string; count: number; label?: string; hint?: string; tone?: "amber"; children: ReactNode }) {
  return (
    <section className="pb-lane" aria-label={label ? `${name}: ${label}` : name} data-tone={count > 0 ? tone : undefined}>
      <header className="pb-lane-head">
        <h2>{name}</h2>
        <span className="pb-count" aria-label={`${count} ${count === 1 ? "job" : "jobs"}`}>
          {count}
        </span>
        {hint && <small>{hint}</small>}
      </header>
      <div className="pb-lane-body">{children}</div>
    </section>
  );
}

// What is written and not made, by episode and chapter. A whole episode or chapter is handed over
// from its head, as one job is from its card.
function PileList({
  pile,
  card,
  carrying,
  agents,
  hand,
  busy,
}: {
  pile: Pile;
  card: (job: ProductionJob, extra?: Partial<JobCardProps>) => ReactNode;
  carrying: Carrying;
  agents: ProductionAgent[];
  hand: (jobs: ProductionJob[], agent: string) => Promise<void>;
  busy: boolean;
}) {
  const [shut, setShut] = useState<Record<string, boolean>>({});
  const head = (id: string, title: string, sub: string, jobs: ProductionJob[], level: "episode" | "chapter") => {
    const label = `${many(jobs.length)} · ${title}`;
    return (
      <div className="pb-group-head" data-level={level}>
        <button
          type="button"
          className="pb-group-name"
          aria-expanded={!shut[id]}
          title={`${title}${sub ? `: ${sub}` : ""}`}
          {...carrying.grip(jobs, label)}
          onKeyDown={(e) => numberKey(e, agents, (agent) => void hand(jobs, agent))}
          onClick={() => !carrying.wasCarried() && setShut((was) => ({ ...was, [id]: !was[id] }))}
        >
          <ChevronRight aria-hidden="true" />
          <b>{title}</b>
          {sub && <span>{sub}</span>}
        </button>
        <span className="pb-count">{jobs.length}</span>
        <button type="button" className="pb-start" disabled={busy} aria-label={`Start all ${jobs.length} of ${title}, each with the agent it is set to`} title="Start them all, each with the agent it is set to" onClick={() => void hand(jobs, "")}>
          <Play aria-hidden="true" />
          Start
        </button>
      </div>
    );
  };
  return (
    <>
      {pile.map((group) => (
        <div key={group.episode.id} className="pb-group">
          {head(group.episode.id, group.episode.title, "", group.jobs, "episode")}
          {!shut[group.episode.id] &&
            group.chapters.map((chapter) => {
              const id = `${group.episode.id}:${chapter.id}`;
              return (
                <div key={id} className="pb-chapter">
                  {head(id, `Chapter ${chapter.n}`, chapter.question, chapter.jobs, "chapter")}
                  {!shut[id] && chapter.jobs.map((job) => card(job, { carrying, plain: true }))}
                </div>
              );
            })}
        </div>
      ))}
    </>
  );
}

// 1 to 9 on something that can be handed over hands it to that agent's row.
function numberKey(e: KeyboardEvent, agents: ProductionAgent[], to: (agent: string) => void) {
  if (e.metaKey || e.ctrlKey || e.altKey || !/^[1-9]$/.test(e.key)) return;
  const agent = agents[Number(e.key) - 1];
  if (!agent) return;
  e.preventDefault();
  to(agent.id);
}

// An agent: what its next jobs run on, how busy it is, and its jobs across the house. While
// something is carried over it, it says what taking it comes to.
function AgentRow({
  agent,
  n,
  queue,
  over,
  carry,
  pick,
  onPick,
  card,
}: {
  agent: ProductionAgent;
  n: number;
  queue: { running: ProductionJob[]; waiting: ProductionJob[] };
  over: boolean;
  carry: Carry | null;
  pick: ModelPick;
  onPick: (pick: ModelPick) => void;
  card: (job: ProductionJob, extra?: Partial<JobCardProps>) => ReactNode;
}) {
  const [all, setAll] = useState(false);
  const waiting = all ? queue.waiting : queue.waiting.slice(0, WAITING_SHOWN);
  const free = agent.ready && agent.running + agent.waiting === 0;
  return (
    <li className="pb-agent" data-agent={agent.id} data-ready={agent.ready ? "" : undefined} data-over={over || undefined} data-target={carry && agent.ready ? "" : undefined}>
      <div className="pb-agent-head">
        <AgentMark mark={agent.id} />
        <b>{agent.title}</b>
        {n > 0 && (
          <kbd className="pb-key" aria-hidden="true">
            {n}
          </kbd>
        )}
        <span className="pb-load" data-free={free || undefined} data-preview={(over && carry) || undefined}>
          {over && carry ? handOverWords(agent, carry.jobs.length, carry.jobs.filter((j) => j.stale).length) : loadOf(agent)}
        </span>
      </div>
      {agent.ready && offersPicks(agent.models) && <RowPick agent={agent} pick={pick} onPick={onPick} />}
      {(queue.running.length > 0 || queue.waiting.length > 0) && (
        <div className="pb-queue" role="group" aria-label={`${agent.title}'s jobs`}>
          {queue.running.map((j) => card(j))}
          {waiting.map((j) => card(j))}
          {queue.waiting.length > WAITING_SHOWN && (
            <button type="button" className="pb-more" aria-expanded={all} onClick={() => setAll((was) => !was)}>
              {all ? "Show fewer" : `+${queue.waiting.length - WAITING_SHOWN} more waiting`}
            </button>
          )}
        </div>
      )}
    </li>
  );
}

// What the jobs handed to an agent from here run on. Left as it is, each job keeps what it is set
// to (its own pick, its film's, or the agent's default); a model or an effort picked here goes
// with every job handed over.
function RowPick({ agent, pick, onPick }: { agent: ProductionAgent; pick: ModelPick; onPick: (pick: ModelPick) => void }) {
  const named = agent.models.filter((m) => m.id);
  const efforts = (agent.models.find((m) => m.id === pick.model) ?? agent.models[0])?.efforts ?? [];
  return (
    <div className="pb-agent-pick">
      <Select
        size="sm"
        aria-label={`Model for what is handed to ${agent.title}`}
        value={pick.model}
        disabled={named.length === 0}
        options={[{ value: "", label: "Each job's model" }, ...named.map((m) => ({ value: m.id, label: optionLabel(m) }))]}
        onChange={(model) => onPick({ model, effort: "" })}
      />
      <Select
        size="sm"
        aria-label={`Effort for what is handed to ${agent.title}`}
        value={efforts.includes(pick.effort) ? pick.effort : ""}
        disabled={efforts.length === 0}
        options={[{ value: "", label: "Its effort" }, ...efforts.map((e) => ({ value: e, label: effortName(e) }))]}
        onChange={(effort) => onPick({ model: pick.model, effort })}
      />
    </div>
  );
}

type JobCardProps = {
  job: ProductionJob;
  view: ProductionView;
  open: boolean;
  onOpen: () => void;
  hand: (jobs: ProductionJob[], agent: string) => Promise<void>;
  busy: boolean;
  picks: Record<string, ModelPick>;
  // set where the card can be carried to an agent
  carrying?: Carrying;
  // in the pile its place is said by the group it is in
  plain?: boolean;
};

// One job: a mark for where it stands, its name, where it is, and one line on how it is going. It
// unfolds in place for what it shows and what can be done about it.
function JobCard({ job, view, open, onOpen, hand, busy, picks, carrying, plain }: JobCardProps) {
  const name = jobName(job);
  const place = jobPlace(job, view.episodes);
  const ready = view.agents.filter((a) => a.ready);
  const face = useRef<HTMLButtonElement>(null);
  return (
    <article
      className="pb-card"
      data-state={job.state}
      data-open={open || undefined}
      data-stale={job.stale || undefined}
      aria-label={name}
      // Escape folds an open card away from anywhere on it, and its face has the focus again
      onKeyDown={(e) => {
        if (e.key !== "Escape" || !open) return;
        e.stopPropagation();
        onOpen();
        face.current?.focus({ preventScroll: true });
      }}
    >
      <button
        ref={face}
        type="button"
        className="pb-face"
        aria-expanded={open}
        title={`${name} · ${place}`}
        {...(carrying ? carrying.grip([job], name) : {})}
        onKeyDown={(e) => {
          if (carrying) numberKey(e, ready, (agent) => void hand([job], agent));
        }}
        onClick={() => !carrying?.wasCarried() && onOpen()}
      >
        <Mark job={job} />
        <span className="pb-name">{name}</span>
        {job.still && job.state === "done" && <img className="pb-still" src={job.still} alt="" loading="lazy" />}
        {!plain && <span className="pb-place">{place}</span>}
        <Standing job={job} view={view} />
      </button>
      {open && <Details job={job} view={view} hand={hand} busy={busy} picks={picks} />}
    </article>
  );
}

// The mark of where a job stands: a ring to make, an arc that turns only while its agent is heard
// from, amber where it waits on the person, red where it stopped, green once done.
function Mark({ job }: { job: ProductionJob }) {
  const doing = useLive(job);
  // the house's own stages (no turn to hear from) turn as its work goes; an agent's turn turns
  // only while it is heard from
  const signal = job.state !== "running" ? undefined : doing?.kind === "lost" ? "lost" : doing && doing.kind !== "thinking" && doing.kind !== "writing" ? "quiet" : "live";
  return <i className="pb-mark" data-signal={signal} aria-hidden="true" />;
}

// What a running job's model is at between two steps, from what was last heard from its turn.
// Between an agent's turns the house does the work itself (it renders, it takes stills): then
// there is no turn to hear from, and what the last one said is over.
function useLive(job: ProductionJob): Now | null {
  const lane = job.what === "script" ? "plan" : `picture:${job.unit}`;
  const told = useHouse((s) => s.pulses[`${job.episode}:${lane}`]);
  const turn = job.state === "running" && job.heard_at !== null;
  const now = useNow(turn);
  if (!turn) return null;
  const pulse = told && (!job.pulse || told.at >= job.pulse.at) ? told : job.pulse;
  return nowOf(now, job.heard_at, pulse, job.tells);
}

// How a job is going, in one line under its name.
function Standing({ job, view }: { job: ProductionJob; view: ProductionView }) {
  const doing = useLive(job);
  const agent = view.agents.find((a) => a.id === job.agent);
  // a made picture says what its record says it ran on; one to come, what it is set to
  const made = job.state === "done" || job.state === "go";
  // the scripted builder runs on no model
  const set = job.agent === "demo" ? "Scripted" : pickLabel(agent?.models, { model: job.model, effort: job.effort });
  const on = made ? madeOn({ provider: job.agent, model: job.model, effort: job.effort }) : set;
  const who = (
    <span className="pb-who">
      <AgentMark mark={job.agent} size="sm" />
      {on || agent?.title || ""}
    </span>
  );
  switch (job.state) {
    case "todo":
      return (
        <span className="pb-standing">
          {job.stale ? <em>Out of date</em> : LEVEL_NAMES[job.level]}
          {who}
        </span>
      );
    case "waiting":
      return <span className="pb-standing">Waiting its turn{who}</span>;
    case "running": {
      const stage = job.what === "script" ? "Writing" : (DOING[job.stage as keyof typeof DOING] ?? "Working");
      const live =
        doing?.kind === "lost" ? (
          <em data-tone="amber">
            No sign of life for <Clock since={doing.since} />
          </em>
        ) : doing?.kind === "thinking" ? (
          <>
            Thinking <Clock since={doing.since} />
          </>
        ) : doing?.kind === "writing" && doing.step ? (
          toolOf(doing.step).verb
        ) : (
          <>
            {stage} {job.started_at ? <Clock since={job.started_at} /> : null}
          </>
        );
      return (
        <span className="pb-standing">
          <span>{live}</span>
          {who}
        </span>
      );
    }
    case "go":
      return (
        <span className="pb-standing" data-tone="amber">
          <span>
            {job.what === "script" ? "Its plan is ready to read" : "Waiting for your go"} {job.ended_at ? <Clock since={job.ended_at} /> : null}
          </span>
        </span>
      );
    case "failed":
      return (
        <span className="pb-standing" data-tone="red">
          <span>{job.failure || "It stopped."}</span>
        </span>
      );
    default:
      return (
        <span className="pb-standing">
          {job.seconds ? `Made in ${took(job.seconds)}` : "Made"}
          {who}
        </span>
      );
  }
}

// A job unfolded: what it shows and says, what its agent is at, and what can be done about it
// here. Its episode opens as a peek over the board, or as its own page.
function Details({ job, view, hand, busy, picks }: { job: ProductionJob; view: ProductionView; hand: (jobs: ProductionJob[], agent: string) => Promise<void>; busy: boolean; picks: Record<string, ModelPick> }) {
  const doing = useLive(job);
  const say = useHouse((s) => s.say);
  const load = useHouse((s) => s.loadProduction);
  const ready = view.agents.filter((a) => a.ready);
  const [to, setTo] = useState(ready.some((a) => a.id === job.agent) ? job.agent : (ready[0]?.id ?? ""));
  const agent = view.agents.find((a) => a.id === to);
  const picture = job.what === "picture";
  const peek = () => void useHouse.getState().openEpisode(job.episode, picture && job.chapter ? { chapter: job.chapter, line: job.unit } : null, true);
  const stop = () =>
    void api
      .stopEpisode(job.episode, job.unit)
      .then(() => load())
      .catch((e: Error) => say(e.message));
  // stopping the writer stops its episode's pictures too, so it is offered only when none is on its way
  const building = view.jobs.some((j) => j.episode === job.episode && j.what === "picture" && (j.state === "running" || j.state === "waiting"));
  // what was picked on that agent's row goes with it; with nothing picked, the job keeps its own
  const pick = picks[to];
  const on = agent && pick && (pick.model || pick.effort) ? pickLabel(agent.models, pick) : "";
  return (
    <div className="pb-details">
      {job.still && <img className="pb-still-wide" src={job.still} alt="" loading="lazy" />}
      {job.shows && <p className="pb-shows">{job.shows}</p>}
      {job.says && <q className="pb-says">{job.says}</q>}
      {job.state === "running" && (doing?.kind === "thinking" && doing.words ? <q className="pb-thought">{tail(doing.words, 220)}</q> : job.doing ? <p className="pb-doing">{job.doing}</p> : null)}
      {job.state === "running" && doing?.kind === "lost" && <p className="pb-doing" data-tone="amber">It is usually heard from more often than this, so it may be stuck.</p>}
      {picture && (job.state === "todo" || job.state === "failed") && ready.length > 0 && (
        <div className="pb-handover">
          <Select size="sm" aria-label="Agent to hand it to" value={to} options={ready.map((a) => ({ value: a.id, label: a.title }))} onChange={setTo} />
          <button type="button" className="btn primary" disabled={busy || !to} onClick={() => void hand([job], to)}>
            {job.state === "failed" ? <RotateCcw aria-hidden="true" /> : <Play aria-hidden="true" />}
            {job.state === "failed" ? "Try again" : job.stale ? "Draw it again" : "Start"}
          </button>
          {on && <small>on {on}</small>}
        </div>
      )}
      <div className="pb-actions">
        <button type="button" className={job.state === "go" ? "btn primary" : "btn"} onClick={peek}>
          {job.state === "go" ? (picture ? "Check its stills" : "Read the plan") : "Open"}
        </button>
        {(job.state === "running" || job.state === "waiting") && (picture || !building) && (
          <button type="button" className="btn" onClick={stop}>
            <Square aria-hidden="true" />
            Stop
          </button>
        )}
        <a className="pb-link" href={jobAddress(job, view.episodes)} onClick={(e) => full(e, job, view.episodes)}>
          Open full page
        </a>
      </div>
    </div>
  );
}

// A job's place in its episode's own page: the link opens it here, unless it is asked for in a
// new tab or window.
function full(e: React.MouseEvent, job: ProductionJob, episodes: ProductionEpisode[]) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  const episode = episodes.find((x) => x.id === job.episode);
  if (!episode) return;
  e.preventDefault();
  const house = useHouse.getState();
  void house.openChannel(episode.channel_id, "canvas");
  void house.openEpisode(job.episode, job.what === "picture" && job.chapter ? { chapter: job.chapter, line: job.unit } : null);
}
