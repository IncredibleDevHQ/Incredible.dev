// What the agent works with, and what waits on people. Each page is one piece of the design
// agent's system map made visible: the brand pack it is staged with, the skills it routes
// through, the computer it works on, and the threads whose work waits on a person.
import { useEffect, useState } from "react";
import { api, type ComputerView, type SkillView } from "../api";
import { useHouse } from "../store";
import { StatusChip } from "../ui";

export function NeedsYou() {
  const { threads, channels } = useHouse();
  const openChannel = useHouse((s) => s.openChannel);
  const openThread = useHouse((s) => s.openThread);
  const waiting = Object.values(threads).filter((t) => t.status === "needs_you");
  const working = Object.values(threads).filter((t) => t.status === "working");
  const row = (t: (typeof waiting)[number]) => {
    const channel = channels.find((c) => c.id === t.channel_id);
    return (
      <button
        type="button"
        key={t.id}
        className="card"
        style={{ textAlign: "left", display: "grid", gap: 6 }}
        onClick={async () => {
          await openChannel(t.channel_id, "canvas");
          await openThread(t.id);
        }}
      >
        <span className="muted" style={{ fontSize: 12 }}>#{channel?.name}</span>
        <h3>{t.title}</h3>
        <StatusChip status={t.status} />
      </button>
    );
  };
  return (
    <section className="page" aria-labelledby="needs-title">
      <h1 id="needs-title">Needs you</h1>
      <p className="lede">Boards waiting for a review or a sign-off, and questions the agent asked. Everything else runs on its own and tells you when it lands.</p>
      {waiting.length ? <div className="cards">{waiting.map(row)}</div> : <p className="muted">Nothing waits on you.</p>}
      {working.length > 0 && (
        <div className="section">
          <h2>Working now</h2>
          <div className="cards">{working.map(row)}</div>
        </div>
      )}
    </section>
  );
}

// The Brand page lives in its own file.
export { Brand } from "./BrandPage";

const ROUTER = new Set(["media-production", "content-brief"]);
const JUDGMENT = new Set(["brand-design", "design-wiki", "visual-verify", "motion-direction", "canvas"]);

export function Skills() {
  const [skills, setSkills] = useState<SkillView[]>([]);
  useEffect(() => {
    void api.skills().then(setSkills);
  }, []);
  const groups: [string, string, SkillView[]][] = [
    ["Routing", "Opened first for every ask: picks the workflow from what the person will receive.", skills.filter((s) => ROUTER.has(s.name))],
    ["Making", "One per kind of output: stills, decks, charts, images, GIFs, thumbnails, storyboards, films, sound.", skills.filter((s) => !ROUTER.has(s.name) && !JUDGMENT.has(s.name) && !s.vendored)],
    ["Judgment", "Beside every job: the concept gate, the design wiki, looking before delivering, and the team's review on the canvas.", skills.filter((s) => JUDGMENT.has(s.name))],
    ["From HyperFrames, unchanged", "Vendored and pinned, never patched: the video engine's own know-how.", skills.filter((s) => s.vendored)],
  ];
  return (
    <section className="page" aria-labelledby="skills-title">
      <h1 id="skills-title">Skills</h1>
      <p className="lede">The agent's workflows. Its always-on prompt stays small: it reads one of these only when a job needs it. Fix a skill once, and every job after it follows.</p>
      {groups.map(([title, line, list]) =>
        list.length ? (
          <div className="section" key={title}>
            <h2>{title}</h2>
            <p className="muted" style={{ margin: "-4px 0 10px", fontSize: 13 }}>{line}</p>
            <div className="cards">
              {list.map((s) => (
                <div className="card" key={s.name}>
                  <h3 className="mono" style={{ fontSize: 13 }}>{s.name}</h3>
                  <p>{s.description}</p>
                </div>
              ))}
            </div>
          </div>
        ) : null,
      )}
    </section>
  );
}

export function Computer() {
  const [info, setInfo] = useState<ComputerView | null>(null);
  useEffect(() => {
    void api.computer().then(setInfo);
  }, []);
  if (!info) return <section className="page" />;
  const pinned = Object.entries(info.pinned);
  return (
    <section className="page" aria-labelledby="computer-title">
      <h1 id="computer-title">The agent's computer</h1>
      <p className="lede">Every thread gets its own computer: a sandbox with a browser, FFmpeg and HyperFrames, built from one pinned recipe. Everything it makes is code in a project folder there, so a change is an edit and a re-render.</p>
      <div className="cards">
        <div className="card">
          <h3>No keys inside</h3>
          <p>Image, voice and fetch tools run beside it with the keys and drop results in as files. The model only ever sees paths.</p>
        </div>
        <div className="card">
          <h3>{info.network.length ? `Network: ${info.network.join(", ")}` : "No network"}</h3>
          <p>{info.network.length ? "Only these hosts are reachable; everything else is denied." : "Nothing from outside arrives except through a host tool, as a file."}</p>
        </div>
        <div className="card">
          <h3>Checks before anything ships</h3>
          <p>Brand, sizes, fonts, contrast and animation determinism are checked in code. Exit 2 means a check couldn't run: reported, never a pass.</p>
        </div>
      </div>
      <div className="section">
        <h2>This machine</h2>
        <dl className="facts">
          <dt>Sandbox</dt>
          <dd>{info.sandbox ?? "not started"}</dd>
          <dt>Image</dt>
          <dd className="mono">{info.image}</dd>
          <dt>Per thread</dt>
          <dd>
            {info.vcpus} vCPU, {info.mem_gib} GiB
          </dd>
        </dl>
      </div>
      {pinned.length > 0 && (
        <div className="section">
          <h2>Pinned toolchain</h2>
          <dl className="facts">
            {pinned.map(([name, version]) => (
              <div key={name} style={{ display: "contents" }}>
                <dt className="mono">{name}</dt>
                <dd className="mono">{version}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
