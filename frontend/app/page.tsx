"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Shell } from "./shell";

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
  if (!user) return <main><Login onLogin={refresh} /></main>;
  return <Shell user={user} onLogout={refresh} />;
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

