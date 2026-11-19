// An empty channel's first screen: the brand its work will wear, then the ways in: research when
// the story is in code, material you already have, or an episode from notes, each with one action. Laid out like
// affectUI's Tips Panel (short steps, one action each); it gives way to the work once there is any.
import { LayoutTemplate, Podcast, Telescope } from "lucide-react";
import { useState } from "react";
import type { Channel } from "../api";
import { useHouse } from "../store";
import { BrandSelect } from "./Brand";
import { ResearchStart } from "./Research";

export function ChannelStart({ channel, inChat }: { channel: Channel; inChat?: boolean }) {
  const setMode = useHouse((s) => s.setMode);
  const pickTemplate = useHouse((s) => s.pickTemplate);
  const startEpisode = useHouse((s) => s.startEpisode);
  const [researching, setResearching] = useState<HTMLElement | null>(null);
  return (
    <section className="start-panel" aria-label={`Start #${channel.name}`}>
      <h2>Start #{channel.name}</h2>
      <div className="start-brand">
        <span>Everything made here wears</span>
        <BrandSelect channel={channel} />
      </div>
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
        <article className="start-way">
          <span className="start-icon">
            <Podcast />
          </span>
          <h3>Make an episode</h3>
          <p>When you have notes and want to explain one idea on camera. It is planned from them, then you record it chapter by chapter.</p>
          <button type="button" className="btn" onClick={() => startEpisode({})}>
            <Podcast />
            Plan an episode
          </button>
        </article>
      </div>
      {inChat && <p className="start-foot">Or ask the agent below and attach what you have.</p>}
      {researching && (
        <ResearchStart channelId={channel.id} anchor={researching} onClose={() => setResearching(null)} onStarted={() => setMode("canvas")} />
      )}
    </section>
  );
}
