// The workspace: where people are needed, what the agent works with, and the channels.
import { BellDot, Cpu, Hash, Moon, Palette, Plus, Sparkles, Sun } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { useHouse, type Page } from "../store";
import { useTheme } from "../theme";
import { Avatar } from "../ui";

export function Sidebar() {
  const { channels, channelId, page, people, session, threads } = useHouse();
  const openChannel = useHouse((s) => s.openChannel);
  const openPage = useHouse((s) => s.openPage);
  const switchPerson = useHouse((s) => s.switchPerson);
  const [menu, setMenu] = useState(false);
  const [adding, setAdding] = useState(false);
  const needs = Object.values(threads).filter((t) => t.status === "needs_you").length;
  const me = session ? people[session.me] : undefined;

  const nav = (target: Page, label: string, icon: React.ReactNode, count?: number) => (
    <button
      type="button"
      className="side-item"
      aria-current={page === target || (target === "brand" && page === "read-brand") ? "page" : undefined}
      onClick={() => openPage(target)}
    >
      {icon}
      <span>{label}</span>
      {count ? <span className="count">{count}</span> : null}
    </button>
  );

  return (
    <nav className="side" aria-label="Workspace">
      <div className="side-top">
        <img src="/house.svg" alt="" />
        <strong>Creative House</strong>
        {/* The demo's agent is scripted: it says so, so its sample work is never taken for the real thing. */}
        {session?.demo && (
          <span className="chip demo-chip" title="A scripted agent makes the same sample work, whatever you bring. No AI runs and nothing costs.">
            Demo
          </span>
        )}
      </div>
      <div className="side-nav">
        {nav("needs", "Needs you", <BellDot />, needs)}
        {nav("brand", "Brand", <Palette />)}
        {nav("skills", "Skills", <Sparkles />)}
        {nav("computer", "Computer", <Cpu />)}
      </div>
      <div className="side-head">
        <span>Channels</span>
        <button type="button" aria-label="New channel" aria-expanded={adding} onClick={() => setAdding(!adding)}>
          <Plus size={15} />
        </button>
      </div>
      <div className="side-channels">
        {adding && <NewChannel onDone={() => setAdding(false)} />}
        {channels.map((c) => (
          <button
            type="button"
            key={c.id}
            className="side-item"
            aria-current={page === "channel" && channelId === c.id ? "page" : undefined}
            onClick={() => openChannel(c.id)}
          >
            <Hash />
            <span>{c.name}</span>
            {c.needs_you ? (
              <span className="count">{c.needs_you}</span>
            ) : c.working ? (
              <span className="dot working" title="The agent is working here" />
            ) : null}
          </button>
        ))}
      </div>
      <div className="side-foot">
        {menu && (
          <div className="menu" role="menu" aria-label="Act as">
            {Object.values(people)
              .filter((p) => !p.agent)
              .map((p) => (
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={session?.me === p.id}
                  key={p.id}
                  onClick={async () => {
                    setMenu(false);
                    await switchPerson(p.id);
                  }}
                >
                  <Avatar person={p} size="sm" />
                  {p.name}
                </button>
              ))}
          </div>
        )}
        <ThemeSwitch />
        <button type="button" className="whoami" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>
          <Avatar person={me} />
          <span>
            {me?.name ?? "You"}
            <small>Switch who you are · local workspace</small>
          </span>
        </button>
      </div>
    </nav>
  );
}

// Light or dark, both named and in sight on every page, the one in use pressed.
function ThemeSwitch() {
  const [theme, setTheme] = useTheme();
  return (
    <div className="seg theme-switch" role="group" aria-label="Appearance">
      <button type="button" aria-pressed={theme === "light"} onClick={() => setTheme("light")}>
        <Sun />
        Light
      </button>
      <button type="button" aria-pressed={theme === "dark"} onClick={() => setTheme("dark")}>
        <Moon />
        Dark
      </button>
    </div>
  );
}

// A channel named in place: what is typed reads as the name it will have (lowercase, dashes).
// Enter makes it and opens it; Escape, or leaving it empty, puts it away.
function NewChannel({ onDone }: { onDone: () => void }) {
  const openChannel = useHouse((s) => s.openChannel);
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const slug = name.replace(/-+$/, "");

  const make = async () => {
    if (!slug || busy) return;
    setBusy(true);
    try {
      const channel = await api.addChannel(slug, topic.trim());
      onDone();
      await openChannel(channel.id);
    } catch (failed) {
      setError((failed as Error).message);
      setBusy(false);
    }
  };
  const keys = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void make();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // only the form: an open thread stays open
      onDone();
    }
  };
  const leave = (e: React.FocusEvent) => {
    if (!name && !e.currentTarget.contains(e.relatedTarget as Node | null)) onDone();
  };
  return (
    <div className="side-new" role="group" aria-label="New channel" onKeyDown={keys} onBlur={leave}>
      <label className="side-new-name">
        <Hash />
        <input
          autoFocus
          value={name}
          maxLength={40}
          disabled={busy}
          placeholder="channel-name"
          aria-label="Channel name"
          onChange={(e) => {
            setName(e.target.value.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+/, ""));
            setError("");
          }}
        />
      </label>
      <input
        className="side-new-topic"
        value={topic}
        maxLength={200}
        disabled={busy}
        placeholder="What it's for (optional)"
        aria-label="What the channel is for"
        onChange={(e) => setTopic(e.target.value)}
      />
      {error && <p className="side-new-error">{error}</p>}
    </div>
  );
}
