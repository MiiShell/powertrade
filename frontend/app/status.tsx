"use client";

import { useEffect, useState } from "react";
import { api, type FmpUsage, type Ready, type SelfCheck } from "./api";

export function Status() {
  const [ready, setReady] = useState<Ready | null>(null);
  const [fmp, setFmp] = useState<FmpUsage | null>(null);
  const [check, setCheck] = useState<SelfCheck | string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api.ready().then((r) => setReady(r.data));
    void api.usage().then((r) => setFmp(r.data?.fmp ?? null));
  }, []);

  async function runCheck() {
    setBusy(true);
    const r = await api.selfcheck();
    setBusy(false);
    setCheck(r.status === 200 && r.data ? r.data : `Fehler (${r.status})`);
  }

  return (
    <div className="panel narrow">
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
      {fmp && (
        <>
          <h2>FMP-Budget</h2>
          {fmp.configured ? (
            <>
              <div className="row"><span>Calls heute</span><span>{fmp.calls_today} / {fmp.daily_limit} (jetzt erlaubt: {fmp.allowed_now})</span></div>
              <div className="row"><span>Bandbreite 30 T.</span><span>{(fmp.bytes_30d / 1048576).toFixed(1)} / {(fmp.bandwidth_limit_30d / 1048576).toFixed(0)} MB</span></div>
              {fmp.blocked_today && <p className="error">Heute gesperrt (429 von FMP)</p>}
            </>
          ) : (
            <p className="muted">Kein API-Key gesetzt (scripts/set-secret.sh fmp_api_key)</p>
          )}
        </>
      )}
      <button onClick={runCheck} disabled={busy}>Selfcheck (Worker + DB)</button>
      {typeof check === "string" && <p className="error">{check}</p>}
      {check && typeof check !== "string" && (
        <p className="ok">Worker, DB-Write, DB-Read ok – {check.latency_ms} ms</p>
      )}
    </div>
  );
}
