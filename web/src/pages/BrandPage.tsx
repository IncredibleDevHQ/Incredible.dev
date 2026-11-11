// The Brand page: the house's brand kits. A rail of kits (the configured pack, and packs read from
// websites, which start from an address at its top) beside the kit itself, laid out as a
// showcase: the brand applied to sample frames first, then colour by role, type set in the pack's
// own faces, logos on their grounds, the rules and words it keeps to, and the site it was read
// from. Every value comes from the pack the engine stages; nothing here is made up but the
// sample frames' placeholder words.
import { Check, CircleAlert, ExternalLink, Globe, Palette, RotateCcw } from "lucide-react";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { api, type BrandPackView, type BrandSummary, type ColourRole } from "../api";
import { contrast, luminance, onColour, pick, rolesOf, useFaces } from "../kit";
import { useHouse } from "../store";
import "../brand.css";

const ROLE_WORDS: Record<ColourRole, [string, string]> = {
  ground: ["Ground", "Behind every frame."],
  ink: ["Ink", "Headlines, text and marks."],
  accent: ["Accent", "The one thing that matters in a frame."],
  muted: ["Muted", "Secondary text and labels."],
  rule: ["Rule", "Lines, dividers and quiet fields."],
};
const host = (url: string) => url.replace(/^https?:\/\//, "").split("/")[0];

export function Brand() {
  const { brands, reads, channels, channelId } = useHouse();
  const loadBrands = useHouse((s) => s.loadBrands);
  const selected = useHouse((s) => s.brandSlug);
  const openBrand = useHouse((s) => s.openBrand);
  const [pack, setPack] = useState<BrandPackView | null>(null);
  // Reads already made when the page opens are not news; one that lands while it's open is.
  const [landed] = useState(() => new Set(reads.filter((r) => r.status === "ready").map((r) => r.url)));

  useEffect(() => {
    void loadBrands();
  }, [loadBrands]);
  useEffect(() => {
    void api.brandPack(selected).then(setPack).catch(() => openBrand("default"));
  }, [selected, brands, openBrand]);
  // A read that lands opens the kit it made, once.
  useEffect(() => {
    for (const r of reads) {
      if (r.status === "ready" && r.slug && !landed.has(r.url)) {
        landed.add(r.url);
        openBrand(r.slug);
      }
    }
  }, [reads, landed, openBrand]);

  const here = channels.find((c) => c.id === channelId);
  return (
    <section className="page kits" aria-labelledby="brand-title">
      <Rail brands={brands} selected={selected} onSelect={openBrand} channelId={channelId ?? ""} />
      {pack && <Kit key={pack.slug} pack={pack} here={here} />}
    </section>
  );
}

// -- the rail: a new kit from a website, reads under way, and the kits ----------------------------

// What a read is doing, in the rail's words.
const READING: Record<string, string> = {
  open: "Opening the site…",
  colours: "Taking its colours…",
  type: "Finding its type…",
  logo: "Finding its logo…",
  pack: "Writing the brand pack…",
};

function Rail({ brands, selected, onSelect, channelId }: { brands: BrandSummary[]; selected: string; onSelect: (slug: string) => void; channelId: string }) {
  const reads = useHouse((s) => s.reads);
  const readBrandFor = useHouse((s) => s.readBrandFor);
  const read = async (address: string) => {
    try {
      await api.readBrand(address, channelId);
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    }
  };
  return (
    <aside className="kit-rail" aria-label="Brand kits">
      <h1 id="brand-title">Brands</h1>
      <button type="button" className="btn primary kit-new" onClick={() => readBrandFor(channelId || null)}>
        <Globe />
        Create a brand from a website
      </button>
      {reads
        .filter((r) => r.status !== "ready")
        .map((r) => (
          <div key={r.url} className={`kit-reading ${r.status}`} role="status">
            {r.status === "reading" ? <span className="spin" /> : <CircleAlert size={15} />}
            <span>
              <b>{host(r.url)}</b>
              {r.status === "reading" ? (
                <button type="button" className="linkish" onClick={() => readBrandFor(r.channel || null)}>
                  {READING[r.step ?? "open"] ?? READING.open}
                </button>
              ) : (
                <small>{r.message}</small>
              )}
            </span>
            {r.status === "failed" && (
              <button type="button" className="icon-btn" aria-label={`Try ${host(r.url)} again`} onClick={() => void read(r.url)}>
                <RotateCcw />
              </button>
            )}
          </div>
        ))}
      <div className="kit-list" role="radiogroup" aria-label="Brands">
        {brands.map((b) => (
          <button type="button" role="radio" key={b.slug} aria-checked={selected === b.slug} className="kit-item" onClick={() => onSelect(b.slug)}>
            <span className="kit-mark" style={{ background: b.ground || "#fff" }}>
              {b.logo ? <img src={b.logo} alt="" /> : <Palette size={16} />}
            </span>
            <span className="kit-item-text">
              <b>{b.name}</b>
              <small>{b.source ? host(b.source) : b.sample ? "Sample pack" : "Configured pack"}</small>
            </span>
            <span className="kit-strip" aria-hidden="true">
              {b.colors.slice(0, 6).map((c) => (
                <i key={c.name} style={{ background: c.value }} />
              ))}
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}

// -- the kit -------------------------------------------------------------------------------------

function Kit({ pack, here }: { pack: BrandPackView; here?: { id: string; name: string; brand?: string } }) {
  const { channels } = useHouse();
  const loadBrands = useHouse((s) => s.loadBrands);
  const type = useFaces(pack);
  const roles = rolesOf(pack);
  const used = channels.filter((c) => (c.brand || "default") === pack.slug);
  const usedHere = here ? (here.brand || "default") === pack.slug : true;
  const mark = pick(pack.logos, "mark", false) ?? pick(pack.logos, "lockup", false);
  const families = [...new Set([pack.stacks.display?.[0], pack.stacks.text?.[0], pack.stacks.mono?.[0]].filter(Boolean))];
  let n = 0;
  const next = () => ++n;

  return (
    <article className="kit" style={type.vars}>
      <style>{type.css}</style>
      <header className="kit-head">
        <span className="kit-mark large" style={{ background: roles.ground || "#fff" }}>
          {mark ? <img src={mark.url} alt="" /> : <Palette size={20} />}
        </span>
        <div className="kit-head-text">
          <h2>{pack.name}</h2>
          {pack.description && <p>{pack.description}</p>}
          <div className="kit-meta">
            {pack.source ? (
              <a href={pack.source} target="_blank" rel="noreferrer">
                {host(pack.source)}
                {pack.read ? ` · read ${pack.read}` : ""}
                <ExternalLink size={12} />
              </a>
            ) : (
              <span>{pack.sample ? "Sample pack" : "Configured pack"}</span>
            )}
            <span className="kit-sep" />
            <span>{used.length ? `Used in ${used.map((c) => `#${c.name}`).join(", ")}` : "Not used in a channel yet"}</span>
          </div>
        </div>
        {here && !usedHere && (
          <button type="button" className="btn primary" onClick={() => void api.wearBrand(here.id, pack.slug).then(() => loadBrands())}>
            <Check />
            Use in #{here.name}
          </button>
        )}
      </header>

      <Section n={next()} title="Brand applied" tag={pack.formats.length ? `${pack.formats.length} sizes` : undefined}>
        <Applied pack={pack} roles={roles} />
        {pack.formats.length > 0 && (
          <div className="formats">
            {pack.formats.map((f) => (
              <span key={f.slug} className="format" title={f.label}>
                <i style={{ aspectRatio: `${f.width} / ${f.height}` }} />
                {f.label.split(",")[0]}
                <small>
                  {f.width}×{f.height}
                </small>
              </span>
            ))}
          </div>
        )}
      </Section>

      <Section n={next()} title="Colour" tag={`${pack.colors.length} colours`}>
        <div className="roles">
          {pack.roles.map((r) => (
            <Swatch key={r.role} name={r.name} value={r.value} large>
              <b>{ROLE_WORDS[r.role][0]}</b>
              <span>{ROLE_WORDS[r.role][1]}</span>
              {roles.ground && (r.role === "ink" || r.role === "accent") && <Contrast fg={r.value} bg={roles.ground} />}
            </Swatch>
          ))}
        </div>
        {pack.palette.length > 0 && (
          <div className="palette">
            {pack.palette.map((c) => (
              <Swatch key={c.name} name={c.name} value={c.value} />
            ))}
          </div>
        )}
      </Section>

      <Section n={next()} title="Type" tag={families.join(" + ")}>
        <div className="type-rows">
          {(["display", "text", "mono"] as const).map((role) => {
            const family = pack.stacks[role]?.[0];
            if (!family) return null;
            const site = pack.stand_ins?.[family];
            const weight = role === "display" ? pack.shape.weights.display : role === "text" ? pack.shape.weights.text : undefined;
            const sample =
              role === "display" ? pack.name : role === "text" ? pack.description || `${pack.name} sets body text in ${family}.` : `${pack.formats[0] ? `${pack.formats[0].width}×${pack.formats[0].height}` : "1920×1080"} · ${roles.accent ?? "#000000"} · tokens.json`;
            return (
              <div key={role} className={`type-row ${role}`}>
                <div className="type-spec">
                  <small>{role === "display" ? "Display" : role === "text" ? "Text" : "Mono"}</small>
                  <b>{family}</b>
                  <span>
                    {[weight && `weight ${weight}`, role === "display" && pack.shape.tracking && `tracking ${pack.shape.tracking}`].filter(Boolean).join(" · ")}
                  </span>
                  {site && <span className="chip">Stands in for {site}</span>}
                </div>
                <p className="type-sample" style={{ fontFamily: type[role], fontWeight: weight, letterSpacing: role === "display" ? pack.shape.tracking : undefined }}>
                  {sample}
                </p>
              </div>
            );
          })}
        </div>
      </Section>

      {pack.logos.length > 0 && (
        <Section n={next()} title="Logos" tag={`${pack.logos.length} files`}>
          <div className="logo-tiles">
            {pack.logos.map((logo) => {
              const dark = /reversed|white|on-dark|dark-bg/i.test(logo.name);
              return (
                <figure key={logo.name} className={/^mark/.test(logo.name) ? "logo-mark" : ""} style={{ background: dark ? roles.ink || "#14161a" : roles.ground || "#fff" }}>
                  <img src={logo.url} alt={logo.name} />
                  <figcaption style={{ color: dark ? roles.ground || "#fff" : roles.muted || "#555" }}>
                    {logo.name.replace(/\.\w+$/, "").replace(/-/g, " ")}
                    <span>{logo.name.split(".").pop()?.toUpperCase()}</span>
                  </figcaption>
                </figure>
              );
            })}
          </div>
        </Section>
      )}

      {(pack.rules.length > 0 || pack.graphic_language) && (
        <Section n={next()} title="Rules" tag={pack.rules.length ? `${pack.rules.length} rules` : undefined}>
          {pack.rules.length > 0 && (
            <ol className="rules">
              {pack.rules.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ol>
          )}
          <Shapes pack={pack} accent={roles.accent} />
          {pack.graphic_language && (
            <details className="kit-more">
              <summary>The graphic language</summary>
              <Prose text={pack.graphic_language} />
            </details>
          )}
        </Section>
      )}

      {(pack.voice_line || pack.banned.length > 0 || pack.voice) && (
        <Section n={next()} title="Voice" tag={pack.banned.length ? `${pack.banned.length} phrases it avoids` : undefined}>
          {pack.voice_line && <blockquote className="voice-line">{pack.voice_line}</blockquote>}
          {pack.banned.length > 0 && <Banned phrases={pack.banned} />}
          {pack.voice && (
            <details className="kit-more">
              <summary>The voice guide</summary>
              <Prose text={pack.voice} />
            </details>
          )}
        </Section>
      )}

      {(pack.reference || pack.source) && (
        <Section n={next()} title="Source" tag={pack.source ? host(pack.source) : undefined}>
          <div className="kit-source">
            {pack.reference && (
              <a className="source-shot" href={pack.reference} target="_blank" rel="noreferrer">
                <span className="source-bar">
                  <i />
                  <i />
                  <i />
                  <small>{host(pack.source)}</small>
                </span>
                <img src={pack.reference} alt={`The first screen of ${host(pack.source)}, as it was read`} />
              </a>
            )}
            <div className="source-notes">
              {pack.source && (
                <p>
                  Read from <a href={pack.source} target="_blank" rel="noreferrer">{pack.source.replace(/^https?:\/\//, "")}</a>
                  {pack.read ? ` on ${pack.read}` : ""}.
                </p>
              )}
              {Object.entries(pack.stand_ins ?? {}).map(([open, site]) => (
                <p key={open}>
                  {site} is licensed to the site, so renders use {open} in its place.
                </p>
              ))}
              {pack.license_note && <p className="faint">{pack.license_note}</p>}
            </div>
          </div>
        </Section>
      )}
    </article>
  );
}

function Section({ n, title, tag, children }: { n: number; title: string; tag?: string; children: ReactNode }) {
  const id = `kit-section-${n}`;
  return (
    <section className="kit-section" aria-labelledby={id}>
      <header>
        <span className="kit-n">{String(n).padStart(2, "0")}</span>
        <h3 id={id}>{title}</h3>
        {tag && <span className="kit-tag">{tag}</span>}
      </header>
      {children}
    </section>
  );
}

// -- the brand applied: three sample frames in the pack's colours, faces, shapes and marks ------

function Applied({ pack, roles }: { pack: BrandPackView; roles: Partial<Record<ColourRole, string>> }) {
  const ground = roles.ground || "#ffffff";
  const ink = roles.ink || "#111111";
  const accent = roles.accent || ink;
  const muted = roles.muted || ink;
  const mark = pick(pack.logos, "mark", false) ?? pick(pack.logos, "lockup", false);
  const reversed = pick(pack.logos, "mark", true) ?? pick(pack.logos, "lockup", true);
  const display: CSSProperties = { fontFamily: "var(--kit-display)", fontWeight: Number(pack.shape.weights.display) || 500, letterSpacing: pack.shape.tracking || undefined };
  const text: CSSProperties = { fontFamily: "var(--kit-text)" };
  const mono: CSSProperties = { fontFamily: "var(--kit-mono)" };
  const radius = pack.shape.radius[1] || "8px";
  const family = pack.stacks.display?.[0] ?? "its display face";
  const line = pack.description.split(/(?<=[.!?])\s/)[0];
  const bars = [0.42, 0.66, 0.54, 0.88, 0.72];
  const series = pack.series.length ? pack.series : [accent];
  // On the dark post, the first brand colour that reads against ink.
  const kicker = [accent, ...series, ...pack.palette.map((c) => c.value)].find((c) => contrast(c, ink) >= 3) ?? ground;
  return (
    <div className="applied">
      <figure className="sample-frame wide">
        <div className="sample-art" style={{ background: ground, color: ink }}>
          {mark && <img className="sample-logo" src={mark.url} alt="" />}
          <div className="sample-copy">
            <strong style={display}>{pack.name}</strong>
            <i className="sample-rule" style={{ background: accent, height: pack.shape.stroke || "2px" }} />
            {line && (
              <span style={{ ...text, color: muted }}>{line.length > 90 ? `${line.slice(0, 88)}…` : line}</span>
            )}
          </div>
        </div>
        <figcaption>Title card · 16:9</figcaption>
      </figure>
      <figure className="sample-frame square">
        <div className="sample-art" style={{ background: ink, color: ground }}>
          {reversed && <img className="sample-logo small" src={reversed.url} alt="" />}
          <div className="sample-copy">
            <small style={{ ...mono, color: kicker }}>Sample</small>
            <strong style={{ ...display, fontSize: "1.45em" }}>A headline set in {family}</strong>
            <span className="sample-pill" style={{ background: accent, color: onColour(accent), borderRadius: pack.shape.pill || radius, ...text }}>
              Learn more
            </span>
          </div>
        </div>
        <figcaption>Post · 1:1</figcaption>
      </figure>
      <figure className="sample-frame wide">
        <div className="sample-art chart" style={{ background: ground, color: ink }}>
          <strong style={{ ...display, fontSize: "1.1em" }}>Sample chart</strong>
          <div className="bars" style={{ borderColor: roles.rule || muted }}>
            {bars.map((h, i) => (
              <span key={i} style={{ height: `${h * 100}%`, background: series[i % series.length], borderRadius: `${pack.shape.radius[0] || "2px"} ${pack.shape.radius[0] || "2px"} 0 0` }} />
            ))}
          </div>
          <div className="bar-labels" style={{ ...mono, color: muted }}>
            {["Mon", "Tue", "Wed", "Thu", "Fri"].map((d) => (
              <span key={d}>{d}</span>
            ))}
          </div>
        </div>
        <figcaption>Chart · 16:9</figcaption>
      </figure>
    </div>
  );
}

// -- the parts -----------------------------------------------------------------------------------

function Swatch({ name, value, large, children }: { name: string; value: string; large?: boolean; children?: ReactNode }) {
  const copy = () => {
    void navigator.clipboard?.writeText(value);
    useHouse.getState().say(`Copied ${value}`);
  };
  return (
    <button type="button" className={`swatch-btn ${large ? "large" : ""}`} onClick={copy} title={`Copy ${value}`}>
      <i style={{ background: value }} className={luminance(value) > 0.92 ? "pale" : ""} />
      <span className="swatch-text">
        {children}
        <span className="swatch-code">
          {name} <span className="mono">{value}</span>
        </span>
      </span>
    </button>
  );
}

function Contrast({ fg, bg }: { fg: string; bg: string }) {
  const ratio = contrast(fg, bg);
  const grade = ratio >= 7 ? "AAA" : ratio >= 4.5 ? "AA" : ratio >= 3 ? "AA large" : "Below AA";
  return (
    <span className={`contrast ${ratio < 3 ? "low" : ""}`} title="Contrast on the ground">
      {ratio.toFixed(1)}:1 · {grade}
    </span>
  );
}

function Shapes({ pack, accent }: { pack: BrandPackView; accent?: string }) {
  const { radius, stroke, space, pill } = pack.shape;
  if (!radius.length && !stroke && !space) return null;
  return (
    <div className="shapes" aria-label="Shapes">
      {[...radius, ...(pill ? [pill] : [])].map((r) => (
        <span key={r} className="shape">
          <i style={{ borderRadius: r, borderColor: accent }} />
          <small>{r === pill ? "pill" : r}</small>
        </span>
      ))}
      {stroke && (
        <span className="shape">
          <i className="stroke" style={{ borderTopWidth: stroke, borderTopColor: accent }} />
          <small>stroke {stroke}</small>
        </span>
      )}
      {space && (
        <span className="shape">
          <i className="space" style={{ backgroundSize: `${space} ${space}` }} />
          <small>{space} grid</small>
        </span>
      )}
    </div>
  );
}

function Banned({ phrases }: { phrases: string[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? phrases : phrases.slice(0, 10);
  return (
    <div className="banned">
      <small>Never says</small>
      {shown.map((p) => (
        <s key={p}>{p}</s>
      ))}
      {phrases.length > 10 && (
        <button type="button" className="linkish" onClick={() => setAll(!all)}>
          {all ? "Fewer" : `+${phrases.length - 10} more`}
        </button>
      )}
    </div>
  );
}

// Markdown, as plain as the packs write it: headings, bullets and paragraphs, with code spans.
function Prose({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let list: ReactNode[] | null = null;
  let para: string[] = [];
  const flush = () => {
    if (para.length) out.push(<p key={out.length}>{inline(para.join(" "))}</p>);
    para = [];
    if (list) out.push(<ul key={out.length}>{list}</ul>);
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (!line.trim()) flush();
    else if (heading) {
      flush();
      if (heading[1].length > 1) out.push(<h4 key={out.length}>{inline(heading[2])}</h4>);
    } else if (bullet) {
      if (para.length) {
        out.push(<p key={out.length}>{inline(para.join(" "))}</p>);
        para = [];
      }
      if (!list) list = [];
      list.push(<li key={list.length}>{inline(bullet[1])}</li>);
    } else {
      if (list) {
        out.push(<ul key={out.length}>{list}</ul>);
        list = null;
      }
      para.push(line.trim());
    }
  }
  flush();
  return <div className="kit-prose">{out}</div>;
}

function inline(text: string): ReactNode[] {
  return text.split(/(`[^`]+`)/).map((part, i) => (part.startsWith("`") && part.endsWith("`") ? <code key={i}>{part.slice(1, -1)}</code> : part.replace(/\*\*/g, "")));
}
