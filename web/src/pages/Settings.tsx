import { Skeleton } from "../components/Skeleton";
import { useEffect, useRef, useState } from "react";
import { api, type ChatDefaults, type Organization } from "../api";
import { InputField as TextField, TextareaField as TextArea } from "../components/ui/InputField";
import { Avatar, AgentMark } from "../ui";
import { EffortSlider } from "../components/episode/GenerationSettings";
import { Members, Logs, LoginProfile } from "./WorkspaceSettings";
import { Usage } from "./Usage";
import { ArrowLeft, BarChart3, Building2, ScrollText, SlidersHorizontal, UserRound } from "lucide-react";
import { ChoiceField as Select } from "../components/ui/ChoiceField";
import "./settings.css";
import { choices, preference, type Preference } from "../preferences";
import {useTheme} from "../theme";
import { useHouse } from "../store";

function Appearance() {
  const [,pick,current] = useTheme();
  return <section className="settings-form"><h2>Appearance</h2>
    <div className="theme-setting"><div><strong>Theme mode</strong><p>Choose an appearance or follow your system.</p></div>
      <div className="theme-choices" role="group" aria-label="Theme mode">
        {(["system","dark","light"] as const).map(mode=><label key={mode} className="theme-option">
          <span className={"theme-preview "+mode} aria-hidden="true"><i/><b/><b/></span>
          <span><input type="radio" name="appearance" checked={current===mode} onChange={()=>pick(mode)}/>{mode[0].toUpperCase()+mode.slice(1)}</span>
        </label>)}
      </div></div></section>;
}

function DeviceSelect({ setting, label }: { setting: Preference; label: string }) {
  const [value, setValue] = useState(() => preference(setting));
  const [error, setError] = useState("");
  return <Select label={label} options={choices[setting]} value={value} error={error} onChange={next => {
    try {
      localStorage.setItem("house:" + setting, next);
      setValue(next);
      if(useHouse.getState().session?.authenticated) void api.logInteraction(setting==="start"?"Change start page":"Change time format").catch(()=>{});
      setError("");
    } catch { setError("Your browser could not save this preference."); }
  }} />;
}

export function SettingsPage({tab = "settings"}: {tab?: "settings" | "profile" | "organization" | "logs" | "usage"}) {
  const authenticated = useHouse(s => s.session?.authenticated);
  const openPage = useHouse(s => s.openPage);
  return <section className="page settings-page" aria-labelledby="settings-title">
    <a className="settings-back" href="/"><ArrowLeft size={14} aria-hidden="true"/>Workspace</a>

    <nav className="settings-tabs" aria-label="Settings sections">
      {([
        ["profile", "Profile", UserRound],
        ["organization", "Organization", Building2],
        ["settings", "Preferences", SlidersHorizontal],
        ["usage", "Usage", BarChart3],
        ["logs","Logs",ScrollText],
      ] as const).filter(([page]) => !["profile","logs"].includes(page) || authenticated).map(([page, label, Icon]) => <a key={page} aria-current={tab === page ? "page" : undefined}
        href={page === "settings" ? "/settings" : "/settings/" + page}
        onClick={event => {
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
          event.preventDefault();
          openPage(page);
        }}><Icon size={15} aria-hidden="true" />{label}</a>)}
    </nav>
    <header className="settings-intro"><h1 id="settings-title">{{profile:"Profile settings",organization:"Organization",settings:"Preferences",usage:"Usage",logs:"Activity logs"}[tab]}</h1>
      <p>{{profile:"Your personal details and sign-in methods.",organization:"Manage project details and member access.",settings:"Choose how Studio looks and behaves on this device.",usage:"Review model activity and estimated costs.",logs:"Review project activity by person and time."}[tab]}</p></header>
    {tab === "settings" && <Appearance/>}
    {tab === "settings" && <section className="settings-form"><h2>On this device</h2>
      <DeviceSelect setting="start" label="Start page when opening the app" />
      <DeviceSelect setting="clock" label="Message time format" />
    </section>}
    {tab === "settings" && authenticated && <ModelDefaults />}
    {tab === "profile" && authenticated && <><ProfileDetails /><LoginProfile /><PasswordSettings /></>}
    {tab === "organization" && <><OrganizationProfile />{authenticated && <Members />}</>}
    {tab === "usage" && <Usage />}
    {tab === "logs" && authenticated && <Logs />}
  </section>;
}

function PasswordSettings() {
  const [hasPassword, setHasPassword] = useState<boolean | null>(null);
  const [verified, setVerified] = useState(false);
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [attempt, retry] = useState(0);
  useEffect(() => {
    let active = true;
    api.passwordState().then(({user}) => {
      if (active) setHasPassword(user.has_password);
    }).catch(() => { if (active) setError("Couldn’t load password settings."); });
    return () => { active = false; };
  }, [attempt]);

  const confirming = hasPassword && !verified;
  return <section className="settings-form"><h2>{hasPassword ? "Update password" : "Password"}</h2>
    {error && <p role="alert">{error}</p>}
    {hasPassword === null ? error
      ? <button className="btn" onClick={() => { setError(""); retry(n => n + 1); }}>Try again</button>
      : <Skeleton label="Loading password settings" shape="form" />
      : <form onSubmit={async event => {
        event.preventDefault();
        if (saving || (confirming ? !current : password.length < 8)) return;
        setSaving(true); setError(""); setMessage("");
        try {
          if (confirming) { await api.verifyPassword(current); setVerified(true); return; }
          await api.savePassword(password, hasPassword ? current : undefined);
          setMessage(hasPassword ? "Password updated." : "Password set.");
          setHasPassword(true); setPassword(""); setCurrent(""); setVerified(false);
        } catch (failed) { setError((failed as Error).message); }
        finally { setSaving(false); }
      }}>
        {confirming && <TextField label="Current password" placeholder="Enter current password" type="password" autoComplete="current-password" required
          value={current} disabled={saving} onChange={e => {setCurrent(e.target.value);setError("");setMessage("");}} />}
        {!confirming && <TextField label="New password" placeholder="Enter new password" hint="Use at least 8 characters." type="password" required
          autoComplete="new-password" minLength={8} maxLength={256} value={password} disabled={saving}
          onChange={event => { setPassword(event.target.value); setError(""); setMessage(""); }} />}
        <div><button className="btn primary" type="submit" disabled={saving || (confirming ? !current : password.length < 8)}>
          {saving ? (confirming ? "Verifying…" : "Saving…") : confirming ? "Confirm current password" : hasPassword ? "Update password" : "Set password"}
        </button> {verified && <button type="button" className="btn" disabled={saving} onClick={() => {
          setVerified(false); setCurrent(""); setPassword(""); setError(""); setMessage("");
        }}>Cancel</button>} <span role="status">{message}</span></div>
      </form>}
  </section>;
}

function OrganizationProfile() {
  const session = useHouse(s => s.session);
  const member = !!session?.projectId && session.projectId !== session.me;
  const [saved, setSaved] = useState<Organization | null>(null);
  const [draft, setDraft] = useState<Organization | null>(null);
  const [revision, retry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api.organization().then(profile => {
      if (active) { setSaved(profile); setDraft(profile); }
    }).catch(() => { if (active) setError("Couldn’t load the organization profile."); });
    return () => { active = false; };
  }, [revision]);
  const update = (field: keyof Organization, value: string) => {
    if (draft) setDraft({...draft, [field]: value});
    setMessage(""); setError("");
  };
  return <section className="settings-form"><h2>General settings</h2>
    {error && <p role="alert">{error}</p>}
    {!draft ? error ? <button className="btn" onClick={() => {setError(""); retry(r => r + 1);}}>Try again</button> :
      <Skeleton label="Loading organization" shape="form" /> :
    <form onSubmit={async event => {
      event.preventDefault();
      if (busy || !draft.name.trim()) return;
      setBusy(true); setMessage(""); setError("");
      try {
        const profile = await api.saveOrganization(draft);
        useHouse.setState(state => ({session: state.session && {...state.session, organizationName: profile.name}}));
        setSaved(profile); setDraft(profile); setMessage("Changes saved.");
      } catch { setError("Couldn’t save your changes. Check the details and try again."); }
      finally { setBusy(false); }
    }}>
      <TextField label="Organization name" placeholder="Organization name" hint="Displayed throughout the workspace." required maxLength={100} value={draft.name} readOnly={member} disabled={busy}
        onChange={e => update("name", e.target.value)} />
      {session?.projectId && <><TextField label="Project ID" hint="Reference used in project URLs." readOnly copyable value={session.projectId}/>
        {session.projectUrl && <div className="setting-row"><span>Project address</span><a className="project-address" href={session.projectUrl} title={session.projectUrl}>{new URL(session.projectUrl).host}</a></div>}</>}
      <TextField label="Website" optional type="url" pattern="https?://.+" maxLength={500} placeholder="https://example.com"
        value={draft.website} readOnly={member} disabled={busy} onChange={e => update("website", e.target.value)} />
      <TextArea label="Description" placeholder="Describe your organization" optional maxLength={500} value={draft.description} readOnly={member} disabled={busy}
        onChange={e => update("description", e.target.value)} />
      <div><button type="submit" className="btn primary" disabled={member || busy || !draft.name.trim() ||
        (saved?.name === draft.name && saved?.description === draft.description && saved?.website === draft.website)}>
        {busy ? "Saving…" : "Save changes"}</button> <span role="status">{message}</span></div>
    </form>}
  </section>;
}

function ProfileDetails() {
  const session = useHouse(s => s.session);
  const person = useHouse(s => s.session ? s.people[s.session.me] : undefined);
  const [name, setName] = useState(person?.name ?? "");
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  if (!person || !session) return null;
  function showPerson(saved: NonNullable<typeof person>) {
    useHouse.setState(s => ({people:{...s.people,[saved.id]:saved},
      session:s.session && {...s.session,people:s.session.people.map(p => p.id === saved.id ? saved : p)}}));
  }
  return <section className="settings-form"><h2>Profile details</h2>
    <div className="profile-photo"><Avatar person={person} /><div>
      <input ref={fileInput} type="file" hidden accept="image/png,image/jpeg,image/webp" aria-label="Avatar image"
        onChange={async event => {
          const file = event.target.files?.[0]; event.target.value = "";
          if (!file) return;
          setError(""); setMessage("");
          if (file.size > 5 * 1024 * 1024) {setError("Choose an image under 5 MB.");return;}
          setBusy(true);
          try { showPerson(await api.uploadAvatar(file)); setMessage("Avatar saved."); }
          catch (failed) { setError((failed as Error).message); }
          finally { setBusy(false); }
        }} />
      <button className="btn" type="button" disabled={busy} onClick={() => fileInput.current?.click()}>
        {person.avatar_file ? "Change avatar" : "Add avatar"}</button>
      <small>JPG, PNG or WebP · up to 5 MB</small>
    </div></div>
    <form onChange={() => {setMessage("");setError("");}} onSubmit={async e => {
      e.preventDefault();
      if (busy || !name.trim()) return;
      setBusy(true); setError(""); setMessage("");
      try {
        const saved = await api.saveProfile(name.trim(), person.hue);
        showPerson(saved);
        setName(saved.name); setMessage("Profile saved.");
      } catch { setError("Couldn’t save your profile. Try again."); }
      finally { setBusy(false); }
    }}>
      <TextField label="Display name" placeholder="Your display name" value={name} required maxLength={100} disabled={busy} onChange={e=>setName(e.target.value)} />
      <TextField label="Primary email" placeholder="No email on file" type="email" readOnly value={session.email ?? ""} />
      {error && <p role="alert">{error}</p>}
      <div><button className="btn primary" disabled={busy || !name.trim() || name.trim()===person.name}>
        {busy ? "Saving…" : "Save profile"}</button> <span role="status">{message}</span></div>
    </form>
  </section>;
}

function ModelDefaults() {
  const [data, setData] = useState<ChatDefaults | null>(null);
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [attempt, retry] = useState(0);
  useEffect(() => {
    let active = true;
    api.modelDefaults().then(value => {
      if (active) { setData(value); setModel(value.model); setEffort(value.effort); }
    }).catch(() => {if (active) setError("Couldn’t load model preferences.");});
    return () => {active = false;};
  }, [attempt]);
  const row = data?.options.find(r => r.id === (model || data.default));
  const providers = [...new Set(["openai", "anthropic", "kimi", ...(data?.options.map(r => r.provider) ?? [])])];
  const providerLabels: Record<string,string> = {openai:"GPT", anthropic:"Claude", kimi:"Kimi",google_genai:"Google",groq:"Groq"};
  const marks: Record<string,string> = {openai:"codex",anthropic:"claude",kimi:"kimi"};
  const choose = (id:string) => {setModel(id); setEffort(""); setMessage("");setError("");};
  return <section className="settings-form"><h2>Chat defaults</h2>
    {error && <p role="alert">{error}</p>}
    {!data ? error ? <button className="btn" onClick={()=>{setError("");retry(n=>n+1);}}>Try again</button>
      : <Skeleton label="Loading models" shape="form" /> :
      <form onSubmit={async e => {
        e.preventDefault();
        if (busy) return;
        setBusy(true);setError("");setMessage("");
        try {
          const saved = await api.saveModelDefaults(model, effort);
          setData({...data,...saved}); setMessage("Defaults saved.");
        } catch {setError("Couldn’t save model preferences. Try again.");}
        finally {setBusy(false);}
      }}>
        <Select className="provider-select" label="Default provider" value={row?.provider ?? ""} disabled={busy}
          options={providers.map(p => {
            const available = data.options.some(r => r.provider === p);
            return {value:p, label: providerLabels[p] ?? p, icon:<AgentMark mark={marks[p]} size="sm" />,
              disabled:!available, description: available ? undefined : "Not configured for chat"};
          })}
          onChange={p=>choose(data.options.find(r=>r.provider===p)?.id ?? "")} />
        <Select label="Default model" disabled={busy} value={row?.id ?? ""}
          options={data.options.filter(r=>r.provider===row?.provider).map(r=>({value:r.id,label:r.name}))} onChange={choose} />
        <EffortSlider efforts={row?.efforts ?? []} value={effort} disabled={busy}
          usual={row?.default_effort} onChange={v=>{setModel(row?.id ?? "");setEffort(v);setMessage("");setError("");}} />
        <div><button className="btn primary" disabled={busy || (data.model === model && data.effort === effort)}>
          {busy ? "Saving…" : "Save defaults"}</button> <span role="status">{message}</span></div>
      </form>}
  </section>;
}
