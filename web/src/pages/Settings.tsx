import { useEffect, useState } from "react";
import { api, type Organization } from "../api";
import { TextArea } from "../components/TextArea";
import { TextField } from "../components/TextField";
import { Usage } from "./Usage";
import { BarChart3, Building2, SlidersHorizontal } from "lucide-react";
import { Select } from "../components/Select";
import { choices, preference, type Preference } from "../preferences";
import { useHouse } from "../store";

function DeviceSelect({ setting, label }: { setting: Preference; label: string }) {
  const [value, setValue] = useState(() => preference(setting));
  const [error, setError] = useState("");
  return <Select label={label} options={choices[setting]} value={value} error={error} onChange={next => {
    try {
      localStorage.setItem("house:" + setting, next);
      setValue(next);
      setError("");
    } catch { setError("Your browser could not save this preference."); }
  }} />;
}

export function SettingsPage({tab = "settings"}: {tab?: "settings" | "organization" | "usage"}) {
  const openPage = useHouse(s => s.openPage);
  return <section className="page settings-page" aria-labelledby="settings-title">
    <h1 id="settings-title">Settings</h1>
    <nav className="settings-tabs" aria-label="Settings sections">
      {([
        ["settings", "Preferences", SlidersHorizontal],
        ["organization", "Organization", Building2],
        ["usage", "Usage", BarChart3],
      ] as const).map(([page, label, Icon]) => <a key={page} aria-current={tab === page ? "page" : undefined}
        href={page === "settings" ? "/settings" : "/settings/" + page}
        onClick={event => {
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
          event.preventDefault();
          openPage(page);
        }}><Icon size={15} aria-hidden="true" />{label}</a>)}
    </nav>
    {tab === "settings" && <section className="settings-form"><h2>On this device</h2>
      <DeviceSelect setting="start" label="Start page when opening the app" />
      <DeviceSelect setting="clock" label="Message time format" />
    </section>}
    {tab === "organization" && <OrganizationProfile />}
    {tab === "usage" && <Usage />}
  </section>;
}

function OrganizationProfile() {
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
  return <section className="settings-form"><h2>Organization profile</h2>
    <p className="muted">Details for this private workspace.</p>
    {error && <p role="alert">{error}</p>}
    {!draft ? error ? <button className="btn" onClick={() => {setError(""); retry(r => r + 1);}}>Try again</button> :
      <p role="status">Loading profile…</p> :
    <form onSubmit={async event => {
      event.preventDefault();
      if (busy || !draft.name.trim()) return;
      setBusy(true); setMessage(""); setError("");
      try {
        const profile = await api.saveOrganization(draft);
        setSaved(profile); setDraft(profile); setMessage("Changes saved.");
      } catch { setError("Couldn’t save your changes. Check the details and try again."); }
      finally { setBusy(false); }
    }}>
      <TextField label="Organization name" required maxLength={100} value={draft.name} disabled={busy}
        onChange={e => update("name", e.target.value)} />
      <TextField label="Website" optional type="url" pattern="https?://.+" maxLength={500} placeholder="https://example.com"
        value={draft.website} disabled={busy} onChange={e => update("website", e.target.value)} />
      <TextArea label="Description" optional maxLength={500} value={draft.description} disabled={busy}
        onChange={e => update("description", e.target.value)} />
      <div><button type="submit" className="btn primary" disabled={busy || !draft.name.trim() ||
        (saved?.name === draft.name && saved?.description === draft.description && saved?.website === draft.website)}>
        {busy ? "Saving…" : "Save changes"}</button> <span role="status">{message}</span></div>
    </form>}
  </section>;
}
