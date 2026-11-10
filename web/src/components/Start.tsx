// An empty channel's first screen: the brand its work will wear, then the two ways in, research
// when the story is in code, or material you already have, each with one action. Laid out like
// affectUI's Tips Panel (short steps, one action each); it gives way to the work once there is any.
import { LayoutTemplate, Palette, Telescope } from "lucide-react";
import { useState } from "react";
import type { Channel } from "../api";
import { useHouse } from "../store";
import { BrandMenu } from "./Brand";
import { ResearchStart } from "./Research";

export function ChannelStart({ channel, inChat }: { channel: Channel; inChat?: boolean }) {
  const brands = useHouse((s) => s.brands);
  const setMode = useHouse((s) => s.setMode);
  const pickTemplate = useHouse((s) => s.pickTemplate);
  const [branding, setBranding] = useState<HTMLElement | null>(null);
  const [researching, setResearching] = useState<HTMLElement | null>(null);
  const worn = brands.find((b) => b.slug === (channel.brand || "default"));
  return (
    <section className="start" aria-label={`Start #${channel.name}`}>
      <h2>Start #{channel.name}</h2>
      <p className="start-brand">
        <span className="start-mark">{worn?.logo ? <img src={worn.logo} alt="" /> : <Palette />}</span>
        <span>
          Everything made here wears <b>{worn?.name ?? "the house brand"}</b>
          {channel.brand ? "." : ", the house default."}
        </span>
        <button type="button" className="linkish" aria-expanded={Boolean(branding)} onClick={(e) => setBranding(branding ? null : e.currentTarget)}>
          {channel.brand ? "Change" : "Pick a brand"}
        </button>
      </p>
      <div className="start-ways">
        <article className="start-way">
          <span className="start-icon">
            <Telescope />
          </span>
          <h3>Research a repository</h3>
          <p>When the story is in code. Claude, Codex or Kimi read it on this computer, and you keep notes to make from.</p>
          <button type="button" className="btn" aria-expanded={Boolean(researching)} onClick={(e) => setResearching(researching ? null : e.currentTarget)}>
            <Telescope />
            Start research
          </button>
        </article>
        <article className="start-way">
          <span className="start-icon">
            <LayoutTemplate />
          </span>
          <h3>Start from material</h3>
          <p>When you have a post, doc, notes or a recording. Pick what it becomes: a launch kit, an explainer, posts.</p>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setMode("canvas");
              pickTemplate({});
            }}
          >
            <LayoutTemplate />
            Choose what to make
          </button>
        </article>
      </div>
      {inChat && <p className="start-foot">Or ask the agent below and attach what you have.</p>}
      {branding && <BrandMenu channel={channel} anchor={branding} onClose={() => setBranding(null)} />}
      {researching && (
        <ResearchStart channelId={channel.id} anchor={researching} onClose={() => setResearching(null)} onStarted={() => setMode("canvas")} />
      )}
    </section>
  );
}
