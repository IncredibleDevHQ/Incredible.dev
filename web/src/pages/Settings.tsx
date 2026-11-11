import { useEffect, useState } from "react";
import { api } from "../api";
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

export function SettingsPage() {
  const model = useHouse(s => s.session?.agent.model);
  const [usage, setUsage] = useState<Awaited<ReturnType<typeof api.usage>> | null>(null);
  const [error, setError] = useState(false);
  const [revision, refresh] = useState(0);
  useEffect(() => {
    let active = true;
    setError(false);
    setUsage(null);
    api.usage().then(result => { if (active) setUsage(result); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [revision]);
  return <section className="page settings-page" aria-labelledby="settings-title">
    <h1 id="settings-title">Settings</h1>
    <section className="section"><h2>On this device</h2>
      <DeviceSelect setting="start" label="Start page when opening the app" />
      <DeviceSelect setting="clock" label="Message time format" />
    </section>
    <section className="section"><h2>Workspace usage</h2>
      <p className="muted">All-time recorded model activity · Current model: {model}</p>
      {error ? <p role="alert">Usage is temporarily unavailable.</p> : !usage ? <p role="status">Checking usage…</p> :
        usage.calls === 0 ? <p>No model calls recorded yet.</p> :
        <dl className="usage-totals">
          <dt>Recorded calls</dt><dd>{usage.calls.toLocaleString()}</dd>
          <dt>Input tokens</dt><dd>{usage.input_tokens.toLocaleString()}</dd>
          <dt>Output tokens</dt><dd>{usage.output_tokens.toLocaleString()}</dd>
          <dt>Estimated cost of priced calls</dt><dd>{usage.unpriced === usage.calls ? "Unavailable" : "$" + usage.usd.toFixed(4)}</dd>
          {usage.unpriced > 0 && <><dt>Calls without pricing</dt><dd>{usage.unpriced}</dd></>}
        </dl>}
      <button className="btn" type="button" disabled={!error && !usage} onClick={() => refresh(n => n + 1)}>Refresh usage</button>
    </section>
  </section>;
}
