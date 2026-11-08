"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, type Ready, type SelfCheck } from "./api";

export default function Home() {
  const [user, setUser] = useState<string | null | undefined>(undefined);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(async () => setVersion((v) => v + 1), []);

  useEffect(() => {
    let active = true;
    void api.me().then((r) => {
      if (active) setUser(r.status === 200 && r.data ? r.data.user : null);
    });
    return () => {
      active = false;
    };
  }, [version]);

  if (user === undefined) return <main className="muted">Lade…</main>;
  return <main>{user ? <Status user={user} onLogout={refresh} /> : <Login onLogin={refresh} />}</main>;
}

function Login({ onLogin }: { onLogin: () => Promise<void> }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    const r = await api.login(String(f.get("username")), String(f.get("password")), String(f.get("totp") ?? ""));
    setBusy(false);
    if (r.status === 204) return onLogin();
    setError(r.status === 429 ? "Zu viele Versuche – bitte später erneut." : "Login fehlgeschlagen.");
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h1>PowerTrade</h1>
      <label>Benutzer<input name="username" autoComplete="username" required /></label>
      <label>Passwort<input name="password" type="password" autoComplete="current-password" required /></label>
      <label>TOTP (falls aktiv)<input name="totp" inputMode="numeric" pattern="\d{6}" autoComplete="one-time-code" /></label>
      {error && <p className="error">{error}</p>}
      <button disabled={busy}>Anmelden</button>
    </form>
  );
}

function Status({ user, onLogout }: { user: string; onLogout: () => Promise<void> }) {
  const [ready, setReady] = useState<Ready | null>(null);
  const [check, setCheck] = useState<SelfCheck | string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api.ready().then((r) => setReady(r.data));
  }, []);

  async function runCheck() {
    setBusy(true);
    const r = await api.selfcheck();
    setBusy(false);
    setCheck(r.status === 200 && r.data ? r.data : `Fehler (${r.status})`);
  }

  return (
    <div className="panel">
      <h1>PowerTrade</h1>
      <p className="muted">Angemeldet als {user}</p>
      <h2>Systemstatus</h2>
      {ready ? (
        Object.entries(ready.checks).map(([k, v]) => (
          <div className="row" key={k}>
            <span>{k}</span>
            <span className={v === "ok" ? "ok" : "fail"}>{v}</span>
          </div>
        ))
      ) : (
        <p className="muted">Lade…</p>
      )}
      <button onClick={runCheck} disabled={busy}>Selfcheck (Worker + DB)</button>
      {typeof check === "string" && <p className="error">{check}</p>}
      {check && typeof check !== "string" && (
        <p className="ok">Worker, DB-Write, DB-Read ok – {check.latency_ms} ms</p>
      )}
      <button className="secondary" onClick={async () => { await api.logout(); await onLogout(); }}>
        Abmelden
      </button>
    </div>
  );
}
