import { type FormEvent, type ReactNode, useEffect, useState } from "react";

export async function authRequest(path: string, body?: unknown) {
  const response = await fetch(`/api/auth/${path}`, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Check your details and try again.");
  return data;
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<"loading" | "ready" | "login" | "error">("loading");
  const [google, setGoogle] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    const boot = async () => {
      setState("loading");
      try {
        const config = await authRequest("config");
        if (!active) return;
        if (!config.enabled) { setState("ready"); return; }
        setGoogle(config.google);
        const response = await fetch("/api/auth/session", { credentials: "same-origin" });
        if (!active) return;
        if (response.ok) setState("ready");
        else if (response.status === 401) setState("login");
        else throw new Error("Sign-in is temporarily unavailable. Please try again.");
      } catch (failed) {
        if (active) { setError((failed as Error).message); setState("error"); }
      }
    };
    void boot();
    const expired = () => setState("login");
    window.addEventListener("incredible:signout", expired);
    return () => { active = false; window.removeEventListener("incredible:signout", expired); };
  }, [retry]);

  if (state === "ready") return children;
  if (state === "login") return <Login google={google} />;
  return <main className="auth-shell"><section className="auth-card" aria-busy={state === "loading"}>
    <img className="auth-mark" src="/house.svg" alt="" />
    <h1>Incredible.dev</h1>
    {state === "loading" ? <p role="status">Opening your workspace…</p> : <><p role="alert">{error}</p><button className="btn primary" onClick={() => setRetry(retry + 1)}>Try again</button></>}
  </section></main>;
}

function Login({ google }: { google: boolean }) {
  const [signup, setSignup] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(new URLSearchParams(window.location.search).has("auth_error") ? "Google sign-in could not be completed. Please try again." : "");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await authRequest(signup ? "signup" : "login", { email: email.trim(), password });
      setPassword("");
      if (result.message) setMessage(result.message);
      else window.location.assign("/"); // Clear all previous workspace state on account changes.
    } catch (failed) { setError((failed as Error).message); }
    finally { setBusy(false); }
  };

  return <main className="auth-shell"><section className="auth-card" aria-labelledby="auth-title">
    <img className="auth-mark" src="/house.svg" alt="" />
    <p className="auth-eyebrow">Incredible.dev</p>
    <h1 id="auth-title">{signup ? "Create your account" : "Welcome back"}</h1>
    <p className="muted">Your ideas, conversations and creations. Your private workspace.</p>
    <button type="button" className="btn auth-google" disabled={!google || busy} onClick={() => window.location.assign("/api/auth/google")}>
      <span aria-hidden="true" className="auth-google-mark">G</span>Continue with Google
    </button>
    {!google && <p className="auth-hint">Google sign-in is not available yet. You can use email below.</p>}
    <div className="auth-divider"><span>or use email</span></div>
    <form onSubmit={submit} aria-busy={busy}>
      <label htmlFor="auth-email">Email</label>
      <input id="auth-email" name="email" type="email" required maxLength={254} autoComplete="email" value={email} disabled={busy} onChange={e => setEmail(e.target.value)} />
      <label htmlFor="auth-password">Password</label>
      <input id="auth-password" name="password" type="password" required minLength={8} maxLength={256} autoComplete={signup ? "new-password" : "current-password"} value={password} disabled={busy} onChange={e => setPassword(e.target.value)} />
      {signup && <p className="auth-hint">Use at least 8 characters. We’ll ask you to confirm your email.</p>}
      {error && <p className="auth-error" role="alert">{error}</p>}
      {message && <p className="auth-message" role="status">{message}</p>}
      <button type="submit" className="btn primary" disabled={busy}>{busy ? "Please wait…" : signup ? "Create account" : "Sign in"}</button>
    </form>
    <p className="auth-switch">{signup ? "Already have an account?" : "New here?"} <button type="button" disabled={busy} onClick={() => {setSignup(!signup);setError("");setMessage("");setPassword("");}}>{signup ? "Sign in" : "Create an account"}</button></p>
  </section></main>;
}
