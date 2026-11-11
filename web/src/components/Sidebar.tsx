// The workspace: where people are needed, what the agent works with, and the channels.
import { BellDot, ChevronsUpDown, Cpu, Hash, LogOut, Moon, Palette, Plus, Settings, Sparkles, Sun } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { api } from "../api";
import { useHouse, type Page } from "../store";
import { useTheme, type Theme } from "../theme";
import { Avatar } from "../ui";
import { authRequest } from "./AuthGate";

export function Sidebar() {
  const { channels, channelId, page, people, session, threads } = useHouse();
  const openChannel = useHouse((s) => s.openChannel);
  const openPage = useHouse((s) => s.openPage);
  const switchPerson = useHouse((s) => s.switchPerson);
  const [menu, setMenu] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [theme, setTheme] = useTheme();
  const account = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const accountId = useId();
  const [adding, setAdding] = useState(false);
  const needs = Object.values(threads).filter((t) => t.status === "needs_you").length;
  const me = session ? people[session.me] : undefined;

  useEffect(() => {
    if (!menu) return;
    const outside = (event: PointerEvent) => {
      if (!account.current?.contains(event.target as Node)) setMenu(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setMenu(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("keydown", escape, true);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("keydown", escape, true);
    };
  }, [menu]);

  const signOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await authRequest("logout", {});
      window.location.assign("/");
    } catch (error) {
      useHouse.getState().say((error as Error).message);
      setSigningOut(false);
    }
  };

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
      <div className="side-foot" ref={account} onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setMenu(false);
      }}>
        <ThemeSwitch theme={theme} onChange={setTheme} />
        <button
          ref={trigger}
          type="button"
          className="whoami"
          aria-label={`Account options for ${me?.name ?? "You"}`}
          aria-expanded={menu}
          aria-controls={menu ? accountId : undefined}
          onClick={() => setMenu(!menu)}
        >
          <Avatar person={me} />
          <span className="account-copy">
            <span className="account-name" title={me?.name ?? "You"}>{me?.name ?? "You"}</span>
            <small>{session?.authenticated ? "Private workspace" : "Local workspace"}</small>
          </span>
          <ChevronsUpDown className="account-chevron" size={16} aria-hidden="true" />
        </button>
        {menu && (
          <div className="menu account-menu" id={accountId} role="group" aria-label="Account options">
            <button type="button" onClick={() => { setMenu(false); openPage("settings"); }}>
              <Settings size={16} aria-hidden="true" /> Settings
            </button>
            <div className="account-actions">
              {session?.authenticated ? (
                <button type="button" disabled={signingOut} onClick={() => void signOut()}>
                  <LogOut size={16} aria-hidden="true" />
                  {signingOut ? "Signing out…" : "Sign out"}
                </button>
              ) : (
                <div role="menu" aria-label="Act as">
                  {Object.values(people).filter((p) => !p.agent).map((p) => (
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
            </div>
          </div>
        )}
      </div>
    </nav>
  );
}

// The same appearance control, with theme state kept while the account panel is closed.
function ThemeSwitch({ theme, onChange }: { theme: Theme; onChange: (theme: Theme) => void }) {
  return (
    <div className="seg theme-switch" role="group" aria-label="Appearance">
      <button type="button" aria-pressed={theme === "light"} onClick={() => onChange("light")}>
        <Sun />
        Light
      </button>
      <button type="button" aria-pressed={theme === "dark"} onClick={() => onChange("dark")}>
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
