// The workspace: where people are needed, what the agent works with, and the channels.
import { BellDot, EllipsisVertical, Cpu, Building2, ChartColumn, Hash, LogOut, Moon, Palette, Plus, Settings, Sparkles, SquareKanban, Sun } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { api } from "../api";
import { needsYou } from "../production";
import { useHouse, type Page } from "../store";
import { useTheme, type Theme } from "../theme";
import { Avatar } from "../ui";
import { isWorkspaceTarget } from "./workspaceTarget";
import { authRequest } from "./AuthGate";

export function Sidebar() {
  const { channels, channelId, page, people, session, threads } = useHouse();
  const openChannel = useHouse((s) => s.openChannel);
  const openPage = useHouse((s) => s.openPage);
  const [menu, setMenu] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [theme, setTheme] = useTheme();
  const account = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const accountId = useId();
  const [adding, setAdding] = useState(false);
  const needs = Object.values(threads).filter((t) => t.status === "needs_you").length;
  // what waits on the person across every episode: a go, a plan to read, a job that stopped
  const jobs = useHouse((s) => needsYou(s.production));
  const me = session ? people[session.me] : undefined;

  const identity = session?.email || me?.name || "You";
  const profileName = me?.name || identity;
  const profileDetail = session?.email && session.email !== profileName ? session.email : session?.organizationName || "Local workspace";

  useEffect(() => {
    if (!menu) return;
    const outside = (event: Event) => {
      if (!event.defaultPrevented && isWorkspaceTarget(event.target) && !account.current?.contains(event.target)) setMenu(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented && isWorkspaceTarget(event.target)) {
        event.preventDefault();
        event.stopPropagation();
        setMenu(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [menu]);

  const signOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try {
      const result = await authRequest("logout", {});
      window.location.assign(result.url ?? "/");
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
          <span className="chip demo-chip" title="Chat uses a scripted demo. Episodes can use a live writer and its model allowance.">
            Demo
          </span>
        )}
      </div>
      <div className="side-nav">
        {nav("needs", "Needs you", <BellDot />, needs)}
        {nav("production", "Production", <SquareKanban />, jobs)}
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
      <div className="side-foot" ref={account}>
        <ThemeSwitch theme={theme} onChange={setTheme} />
        <button
          ref={trigger}
          type="button"
          className="whoami"
          aria-label={`Account options for ${identity}`}
          aria-expanded={menu}
          aria-controls={menu ? accountId : undefined}
          onClick={() => setMenu(!menu)}
        >
          <Avatar person={me} />
          <span className="account-copy">
            <span className="account-name" title={profileName}>{profileName}</span>
            <small title={profileDetail}>{profileDetail}</small>
          </span>
          <EllipsisVertical className="account-chevron" size={16} aria-hidden="true" />
        </button>
        {menu && (
          <div className="menu account-menu" id={accountId} role="group" aria-label="Account options">
            <button type="button" onClick={() => { setMenu(false); openPage("profile"); }}>
              <Settings size={16} aria-hidden="true" /> Settings
            </button>
            <button type="button" onClick={() => { setMenu(false); openPage("organization"); }}>
              <Building2 size={16} aria-hidden="true" /> Organization
            </button>
            <button type="button" onClick={() => { setMenu(false); openPage("usage"); }}>
              <ChartColumn size={16} aria-hidden="true" /> Usage
            </button>
            <div className="account-actions">
              <button type="button" disabled={!session?.authenticated || signingOut}
                title={session?.authenticated ? undefined : "This local workspace has no signed-in account."}
                onClick={() => void signOut()}>
                <LogOut size={16} aria-hidden="true" />
                {signingOut ? "Logging out…" : "Log out"}
              </button>
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
