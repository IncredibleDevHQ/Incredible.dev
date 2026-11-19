// The production board's own reckoning: which lane a job stands in, how the jobs to make are
// grouped (an episode, then its chapters), what a filter keeps, where a job is, and what handing
// some to an agent comes to before it is done. Nothing here draws; the board
// (pages/Production.tsx) does.
import type { JobState, ProductionAgent, ProductionEpisode, ProductionJob, ProductionView } from "./api";

// The lanes, in the order work moves through them: what is written and not made, what the agents
// have (running, and waiting its turn), what waits on the person, what is done.
export type Lane = "todo" | "agents" | "needs" | "done";
const LANE_OF: Record<JobState, Lane> = { todo: "todo", waiting: "agents", running: "agents", go: "needs", failed: "needs", done: "done" };
export const laneOf = (job: ProductionJob): Lane => LANE_OF[job.state];

// What the board is narrowed to: one episode, one of its chapters, one agent. "" is all of them.
export type BoardFilter = { episode: string; chapter: string; agent: string };
export const NO_FILTER: BoardFilter = { episode: "", chapter: "", agent: "" };

export function kept(jobs: ProductionJob[], filter: BoardFilter): ProductionJob[] {
  return jobs.filter(
    (j) =>
      (!filter.episode || j.episode === filter.episode) &&
      // a chapter is one episode's; the script is the whole episode's, so a chapter leaves it out
      (!filter.chapter || (Boolean(filter.episode) && j.chapter === filter.chapter)) &&
      (!filter.agent || j.agent === filter.agent),
  );
}

// Where a job is: its episode and, for a picture, its chapter by number.
export function jobPlace(job: ProductionJob, episodes: ProductionEpisode[]): string {
  const episode = episodes.find((e) => e.id === job.episode);
  const chapter = episode?.chapters.find((c) => c.id === job.chapter);
  return [episode?.title ?? "", chapter ? `Chapter ${chapter.n}` : ""].filter(Boolean).join(" · ");
}

// The jobs to make as the pile shows them: by episode, then by chapter, in the film's order.
export type Pile = { episode: ProductionEpisode; jobs: ProductionJob[]; chapters: { id: string; n: number; question: string; jobs: ProductionJob[] }[] }[];
export function pileOf(jobs: ProductionJob[], episodes: ProductionEpisode[]): Pile {
  return episodes.flatMap((episode) => {
    const mine = jobs.filter((j) => j.episode === episode.id && j.state === "todo" && j.what === "picture");
    if (mine.length === 0) return [];
    const chapters = episode.chapters.flatMap((c) => {
      const inIt = mine.filter((j) => j.chapter === c.id);
      return inIt.length ? [{ ...c, jobs: inIt }] : [];
    });
    return [{ episode, jobs: chapters.flatMap((c) => c.jobs), chapters }];
  });
}

// An agent's jobs as its row shows them: the ones running first, then the ones waiting, each in
// the order they were asked for.
export function queueOf(jobs: ProductionJob[], agent: string): { running: ProductionJob[]; waiting: ProductionJob[] } {
  const mine = jobs.filter((j) => j.agent === agent && laneOf(j) === "agents");
  const asked = (a: ProductionJob, b: ProductionJob) => (a.asked_at ?? a.started_at ?? 0) - (b.asked_at ?? b.started_at ?? 0);
  return { running: mine.filter((j) => j.state === "running").sort(asked), waiting: mine.filter((j) => j.state === "waiting").sort(asked) };
}

// How busy an agent is, in a few words: nothing of its own means it is free.
export function loadOf(agent: ProductionAgent): string {
  if (!agent.ready) return "Not set up here";
  const parts = [agent.running ? `${agent.running} running` : "", agent.waiting ? `${agent.waiting} waiting` : ""].filter(Boolean);
  return parts.join(" · ") || "Free";
}

// How many of an agent's jobs build at once across the house (the rest wait their turn).
export const AT_ONCE = 4;

// What handing `count` pictures to an agent comes to, said before it is done: how many, how many
// of them are made already and would be drawn again, and about how long until the last is made,
// where its earlier pictures say how long one takes.
export function handOverWords(agent: ProductionAgent, count: number, again = 0): string {
  const many = `+${count} ${count === 1 ? "picture" : "pictures"}${again ? ` · ${again === count ? (count === 1 ? "drawn again" : "all drawn again") : `${again} drawn again`}` : ""}`;
  if (!agent.seconds) return many;
  const ahead = agent.running + agent.waiting;
  // they are built a few at a time, so the queue moves in rounds
  const rounds = Math.ceil((ahead + count) / AT_ONCE);
  const minutes = Math.max(1, Math.round((rounds * agent.seconds) / 60));
  return `${many} · about ${minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`}`;
}

// What needs the person, counted: a go, a plan to read, a job that stopped.
export const needsYou = (view: ProductionView | null): number => (view?.jobs ?? []).filter((j) => laneOf(j) === "needs").length;

// The address of a job's place in its episode's own page: its chapter, and the line its picture
// starts on.
export function jobAddress(job: ProductionJob, episodes: ProductionEpisode[]): string {
  const episode = episodes.find((e) => e.id === job.episode);
  if (!episode) return "/";
  const at = job.what === "picture" && job.chapter ? `?at=${encodeURIComponent(job.chapter)}&line=${encodeURIComponent(job.unit)}` : "";
  return `/c/${encodeURIComponent(episode.channel)}/episode/${encodeURIComponent(episode.id)}${at}`;
}
