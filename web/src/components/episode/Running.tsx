// What runs for the episode now, in the bar: one pill, there only while something runs, that says
// how many and opens onto each as a row. A picture being made says where its build is (its stages
// as a strip that fills), who builds it on what and how long it has run; its row opens its beat,
// and it is stopped from there. The writer's turn on the script and the film being rendered say
// what they are on. Nothing else in the studio waits on them: this is where to look. Written for
// this house from notes on how lists of an agent's tasks behave; no other component's source is
// in it.
import { ChevronDown, Clapperboard, Square } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, type EpisodeUnit, type EpisodeView, type Level } from "../../api";
import { doingNow, PICTURES, runningTasks } from "../../episode";
import { useHouse } from "../../store";
import { AgentMark } from "../../ui";
import { Clock } from "../agent/Clock";
import { Popover } from "../Popover";
import { Tooltip } from "../Tooltip";
import { WORKING } from "./Ask";
import { RENDER_PHASES, writerTitle, type Open } from "./Film";
import { builtOn } from "./models";
import { KindArt } from "./PictureArt";
import { FILM } from "./Slides";
import { Swap } from "./Tiles";
import { BUILD } from "./Work";

export function RunningPill({ view, onAt }: { view: EpisodeView; onAt: Open }) {
  const [open, setOpen] = useState(false);
  const pill = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const tasks = runningTasks(view);
  // A row that ends (stopped from its own button, or done) takes the focus with it: the list
  // takes it, so Escape still closes the list and not what is under it.
  const rows = tasks.map((t) => t.id).join(" ");
  useEffect(() => {
    if (open && document.activeElement === document.body) list.current?.focus({ preventScroll: true });
  }, [open, rows]);
  // open on the last task as it ends, it stays to say so; closed, it goes with the last task
  if (tasks.length === 0 && !open) return null;
  const pictures = tasks.flatMap((t) => (t.kind === "picture" ? [t] : []));
  const waiting = pictures.filter((t) => t.waiting).length;
  const under = tasks.length - waiting;
  const words = tasks.length === 0 ? "Done" : under > 0 ? `${under} running` : `${waiting} waiting`;
  const stop = (unit = "") => void api.stopEpisode(view.id, unit).catch((e: Error) => useHouse.getState().say(e.message));
  const chapters = view.plan?.chapters ?? [];
  const number = (u: EpisodeUnit) => chapters.findIndex((c) => c.id === u.chapter) + 1;
  const go: Open = (...to) => {
    setOpen(false);
    onAt(...to);
  };
  const film = view.film_state;
  // what the stop without a name stops: the writer's turn and every picture
  const stoppable = pictures.length + (tasks.some((t) => t.kind === "writer") ? 1 : 0);
  return (
    <span className="ep-work">
      <button ref={pill} type="button" className="ep-work-pill ep-running" data-idle={tasks.length === 0 || undefined} aria-haspopup="dialog" aria-expanded={open} aria-label={`Running now: ${words}`} onClick={() => setOpen((o) => !o)}>
        {tasks.length > 0 && <i className="ep-working" aria-hidden="true" />}
        <Swap swapKey={words} className="ep-work-words">
          {words}
        </Swap>
        <ChevronDown />
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchor={pill}
        side="bottom"
        align="end"
        offset={8}
        width={420}
        ref={list}
        className="ep-run-pop"
        title="Running now"
        description={waiting > 0 && under > 0 ? `${under} under way · ${waiting} waiting ${waiting === 1 ? "its" : "their"} turn` : undefined}
      >
        {tasks.length === 0 ? (
          <p className="ep-run-none" role="status">
            Nothing is running now.
          </p>
        ) : (
          <ul className="ep-run-list">
            {tasks.map((task) => {
              if (task.kind === "picture") {
                const u = task.unit;
                const name = PICTURES[u.kind_of_picture] ?? "Picture";
                return <PictureTask key={task.id} view={view} unit={u} waiting={task.waiting} title={`Chapter ${number(u)} · ${name}`} onOpen={() => go(u.chapter, false, u.frames[0], true)} onStop={() => stop(u.id)} />;
              }
              if (task.kind === "writer") {
                const by = view.working?.harness ?? view.writer;
                return (
                  <TaskRow
                    key={task.id}
                    icon={<AgentMark mark={by} size="sm" />}
                    title="The script"
                    doing={WORKING[view.stage.name ?? ""] ?? "Working"}
                    who={writerTitle(by)}
                    since={view.stage.at}
                    // the stop that names no picture stops the pictures too, so it is the writer's own only alone
                    onStop={pictures.length === 0 ? () => stop() : undefined}
                    stopLabel="Stop the writer"
                  />
                );
              }
              const percent = Math.round(100 * (film.fraction ?? 0));
              return (
                <TaskRow
                  key={task.id}
                  icon={<Clapperboard aria-hidden="true" />}
                  title="The film"
                  doing={RENDER_PHASES[film.phase ?? ""] ?? "Rendering film"}
                  who={`${percent}%`}
                  since={film.started_at}
                  onOpen={() => go(FILM)}
                  strip={
                    <>
                      <i data-state="done" style={{ flex: `0 0 ${percent}%` }} />
                      <i data-state="pending" />
                    </>
                  }
                />
              );
            })}
          </ul>
        )}
        {stoppable > 1 && (
          <footer className="ep-run-foot">
            <button type="button" className="btn" onClick={() => stop()}>
              <Square />
              Stop all
            </button>
          </footer>
        )}
      </Popover>
    </span>
  );
}

// A picture being made, as a task: its build's stages as a strip, the one under way in a word.
function PictureTask({ view, unit, waiting, title, onOpen, onStop }: { view: EpisodeView; unit: EpisodeUnit; waiting: boolean; title: string; onOpen: () => void; onStop: () => void }) {
  const p = unit.picture;
  // a build waiting its turn is still the last build's on record: what it will be is the beat's
  const builder = waiting ? unit.builder : p.builder || unit.builder;
  const level: Level = p.level || unit.level;
  const still = p.stills[unit.frames[0]] ?? Object.values(p.stills)[0];
  const order = BUILD[level];
  const at = order.findIndex((s) => p.stages.find((x) => x.id === s.id)?.state === "running");
  return (
    <TaskRow
      icon={still ? <img src={still.url} alt="" loading="lazy" /> : <KindArt kind={unit.kind_of_picture} />}
      picture
      title={title}
      doing={doingNow(unit, view)}
      who={[writerTitle(builder), builtOn(view, unit, builder)].filter(Boolean).join(" · ")}
      mark={<AgentMark mark={builder} size="sm" />}
      since={waiting ? undefined : (p.timing?.started_at ?? undefined)}
      step={!waiting && at >= 0 ? `step ${at + 1} of ${order.length}` : undefined}
      onOpen={onOpen}
      onStop={onStop}
      stopLabel={`Stop ${title}`}
      strip={order.map((s) => (
        <i key={s.id} data-state={waiting ? "pending" : (p.stages.find((x) => x.id === s.id)?.state ?? "pending")} title={s.label} />
      ))}
    />
  );
}

// One task as a row: what it is about, what it is on and who does it, how long it has run, its
// progress as a strip, and its stop where it has one. A row with somewhere to go opens it.
function TaskRow({
  icon,
  picture,
  title,
  doing,
  who,
  mark,
  since,
  step,
  strip,
  onOpen,
  onStop,
  stopLabel,
}: {
  icon: ReactNode;
  picture?: boolean;
  title: string;
  doing: string;
  who: string;
  mark?: ReactNode;
  since?: number | null;
  // where it is among its steps, for a screen reader: the strip shows it to the eye
  step?: string;
  strip?: ReactNode;
  onOpen?: () => void;
  onStop?: () => void;
  stopLabel?: string;
}) {
  const body = (
    <>
      <span className="ep-run-icon" data-picture={picture || undefined} aria-hidden="true">
        {icon}
      </span>
      <span className="ep-run-words">
        <b>{title}</b>
        <span>
          <em>{doing}</em>
          {mark}
          <span>{who}</span>
        </span>
      </span>
      {since ? <Clock since={since} /> : null}
    </>
  );
  const said = `${title}: ${[doing, step, who].filter(Boolean).join(", ")}`;
  return (
    <li className="ep-run-row">
      {onOpen ? (
        <button type="button" className="ep-run-open" aria-label={`${said}. Open it`} onClick={onOpen}>
          {body}
        </button>
      ) : (
        <div className="ep-run-open" role="group" aria-label={said}>
          {body}
        </div>
      )}
      {onStop && (
        <Tooltip content="Stop it" side="left">
          <button type="button" className="icon-btn ep-run-stop" aria-label={stopLabel} onClick={onStop}>
            <Square />
          </button>
        </Tooltip>
      )}
      {strip && (
        <span className="ep-run-strip" aria-hidden="true">
          {strip}
        </span>
      )}
    </li>
  );
}
