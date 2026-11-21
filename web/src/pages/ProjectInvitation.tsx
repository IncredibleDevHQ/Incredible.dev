import { useEffect, useState } from "react";
import { api } from "../api";
import { authRequest } from "../components/AuthGate";

export function ProjectInvitation({id}: {id: string}) {
  const [invitation, setInvitation] = useState<{organization:string; accepted:boolean} | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, reload] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    api.previewInvitation(id).then(result => { if (active) setInvitation(result); })
      .catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [id, revision]);

  async function accept() {
    setBusy(true);
    setError("");
    try {
      const {url} = await api.enterProject(id);
      window.location.replace(url + "/settings/organization");
    } catch (reason) {
      setError((reason as Error).message);
      setBusy(false);
    }
  }
  async function switchAccount() {
    setBusy(true);
    try {
      await authRequest("logout", {});
      window.location.reload();
    } catch (reason) {
      setError((reason as Error).message);
      setBusy(false);
    }
  }
  return <main className="auth-shell"><section className="auth-card" aria-labelledby="invitation-title">
    <img className="auth-mark" src="/house.svg" alt="" />
    <h1 id="invitation-title">{invitation?.organization ?? "Project invitation"}</h1>
    {invitation ? <>
      <p>{invitation.accepted ? "You’re a member of this project." : "You’ve been invited to join this project as a member."}</p>
      <button className="btn primary" disabled={busy} onClick={accept}>
        {busy ? "Opening…" : invitation.accepted ? "Open project" : "Accept invitation"}
      </button>
    </> : !error && <p role="status">Loading invitation…</p>}
    {error && <p role="alert">{error}</p>}
    {error && !invitation && <button className="btn" disabled={busy} onClick={() => reload(n => n + 1)}>Try again</button>}
    {(invitation || error) && <button className="btn" disabled={busy} onClick={switchAccount}>Use another account</button>}
  </section></main>;
}
