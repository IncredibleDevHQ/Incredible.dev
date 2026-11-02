// What the agent works with, and what waits on people. Each page is one piece of the design
// agent's system map made visible: the brand pack it is staged with, the skills it routes
// through, the computer it works on, and the threads whose work waits on a person.
import { Check, CircleAlert, Globe, Palette } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type BrandPackView, type ComputerView, type SkillView } from "../api";
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

// The brands a channel can wear: the configured pack, and packs read from websites. A read runs
// in a throwaway container and lands here when it is made; the pack shows what renders will use
// (licensed faces named beside the open faces that stand in for them).
export function Brand() {
  const { brands, reads, channels, channelId } = useHouse();
  const loadBrands = useHouse((s) => s.loadBrands);
  const [selected, setSelected] = useState<string>("default");
  const [pack, setPack] = useState<BrandPackView | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void loadBrands();
  }, [loadBrands]);
  useEffect(() => {
    setPack(null);
    void api.brandPack(selected).then(setPack).catch(() => setSelected("default"));
  }, [selected, brands]);

  const read = async () => {
    if (!url.trim()) return;
    setBusy(true);
    try {
      await api.readBrand(url.trim(), channelId ?? "");
      setUrl("");
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const wearing = (slug: string) => channels.filter((c) => (c.brand || "default") === slug);
  const here = channels.find((c) => c.id === channelId);

  return (
    <section className="page" aria-labelledby="brand-title">
      <h1 id="brand-title">Brands</h1>
      <p className="lede">A channel's brand is staged before every run in it. Read one from a website, or keep the configured pack.</p>
      <form
        className="brand-read"
        onSubmit={(e) => {
          e.preventDefault();
          void read();
        }}
      >
        <Globe size={16} />
        <input value={url} placeholder="A website, like yourcompany.com" aria-label="A website to read a brand from" onChange={(e) => setUrl(e.target.value)} />
        <button type="submit" className="btn primary" disabled={!url.trim() || busy}>
          Read its brand
        </button>
      </form>
      {here && <p className="brand-read-note faint">It will be worn in #{here.name} once it is read.</p>}
      {reads
        .filter((r) => r.status !== "ready")
        .map((r) => (
          <p key={r.url} className={`brand-read-status ${r.status}`}>
            {r.status === "reading" ? <span className="spin" /> : <CircleAlert size={14} />}
            <span>{r.status === "reading" ? `Reading ${r.url.replace(/^https?:\/\//, "")}…` : r.message}</span>
          </p>
        ))}
      <div className="brand-list" role="radiogroup" aria-label="Brands">
        {brands.map((b) => (
          <button type="button" role="radio" key={b.slug} aria-checked={selected === b.slug} className="brand-card" onClick={() => setSelected(b.slug)}>
            <span className="brand-card-mark">{b.logo ? <img src={b.logo} alt="" /> : <Palette size={18} />}</span>
            <span className="brand-card-text">
              <b>{b.name}</b>
              <small>{b.source ? `From ${b.source.replace(/^https?:\/\//, "").split("/")[0]}` : b.sample ? "The sample pack" : "The configured pack"}</small>
            </span>
            <span className="brand-card-swatches" aria-hidden="true">
              {b.colors.slice(0, 5).map((c) => (
                <i key={c.name} style={{ background: c.value }} />
              ))}
            </span>
          </button>
        ))}
      </div>
      {pack && (
        <>
          <div className="brand-head">
            <h2>{pack.name}</h2>
            <span className="faint">
              {wearing(pack.slug).length ? `Worn in ${wearing(pack.slug).map((c) => `#${c.name}`).join(", ")}` : "Worn in no channel"}
              {pack.read ? ` · read ${pack.read}` : ""}
            </span>
            {here && (here.brand || "default") !== pack.slug && (
              <button type="button" className="btn" onClick={() => void api.wearBrand(here.id, pack.slug).then(() => loadBrands())}>
                <Check />
                Wear in #{here.name}
              </button>
            )}
          </div>
          <div className="section">
            <h2>Colours</h2>
            <div className="swatches">
              {pack.colors.map((c) => (
                <div className="swatch" key={c.name}>
                  <i style={{ background: c.value }} />
                  <div>
                    <b>{c.name}</b>
                    <span className="mono faint">{c.value}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="section">
            <h2>Type</h2>
            <div className="cards">
              {pack.families.map((f) => (
                <div className="card" key={f.family}>
                  <h3 style={{ fontFamily: `"${f.family}", var(--font)` }}>{f.family}</h3>
                  <p>
                    {pack.stand_ins?.[f.family] ? `Stands in for ${pack.stand_ins[f.family]}, which the site licenses · ` : ""}
                    {f.styles.join(" · ")}
                    {f.license ? ` · ${f.license}` : ""}
                    {f.required ? "" : " · optional"}
                  </p>
                </div>
              ))}
            </div>
          </div>
          {pack.logos.length > 0 && (
            <div className="section">
              <h2>Logos</h2>
              <div className="logos">
                {pack.logos.map((logo) => (
                  <figure key={logo.name} className={/reversed|white/i.test(logo.name) ? "on-ink" : ""}>
                    <img src={logo.url} alt={logo.name} />
                  </figure>
                ))}
              </div>
            </div>
          )}
          {pack.reference && (
            <div className="section">
              <h2>The site, as it was read</h2>
              <img className="brand-reference" src={pack.reference} alt={`The first screen of ${pack.source}`} />
            </div>
          )}
          {pack.voice && (
            <div className="section">
              <h2>Voice</h2>
              <div className="prose">{pack.voice}</div>
            </div>
          )}
          {pack.graphic_language && (
            <div className="section">
              <h2>Graphic language</h2>
              <div className="prose">{pack.graphic_language}</div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

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
