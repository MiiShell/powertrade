"use client";

import { useEffect, useState } from "react";
import { api, type AiUsage, type Analysis, type AnalysisSummary } from "./api";

const TREND: Record<string, string> = { up: "Aufwärts", down: "Abwärts", sideways: "Seitwärts" };
const STRENGTH: Record<string, string> = { weak: "schwach", moderate: "mittel", strong: "stark" };
const CONF: Record<string, string> = { low: "niedrig", medium: "mittel", high: "hoch" };
const SCEN: Record<string, string> = { bull: "Bull", base: "Base", bear: "Bear" };
const STATUS: Record<string, string> = {
  queued: "In Warteschlange…", running: "Claude analysiert… (ca. 20–90 s)", done: "Fertig", refused: "Abgelehnt", failed: "Fehlgeschlagen",
};
const nf = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "–" : v.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });
const usd = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${nf(v, v < 0.1 ? 3 : 2)} $`);

export function AnalysisPanel({ instrumentId, tf, getImage, onAddLevel }: {
  instrumentId: number;
  tf: "1d" | "1w";
  getImage: () => string | null;
  onAddLevel: (price: number, kind: "support" | "resistance") => void;
}) {
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [model, setModel] = useState("claude-opus-5-5");
  const [current, setCurrent] = useState<Analysis | null>(null);
  const [history, setHistory] = useState<AnalysisSummary[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    void api.aiUsage().then((r) => active && r.data && setUsage(r.data));
    void api.analyses(instrumentId).then((r) => active && setHistory(r.data?.analyses ?? []));
    return () => {
      active = false;
    };
  }, [instrumentId, version]);

  // Poll the running analysis.
  const pendingId = current && (current.status === "queued" || current.status === "running") ? current.id : null;
  useEffect(() => {
    if (pendingId === null) return;
    let active = true;
    const t = setInterval(() => {
      void api.analysis(pendingId).then((r) => {
        if (!active || !r.data) return;
        setCurrent(r.data);
        if (r.data.status !== "queued" && r.data.status !== "running") setVersion((v) => v + 1);
      });
    }, 2500);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [pendingId]);

  async function start() {
    setMsg(null);
    const image = getImage();
    if (!image) {
      setMsg("Chart-Screenshot nicht möglich (Chart noch nicht geladen?)");
      return;
    }
    const r = await api.startAnalysis(instrumentId, { tf, model, image });
    if (r.status !== 202 || !r.data) {
      const d = (r.data as unknown as { detail?: unknown } | null)?.detail;
      setMsg(`Fehler ${r.status}${typeof d === "string" ? `: ${d}` : ""}`);
      return;
    }
    const a = await api.analysis(r.data.id);
    setCurrent(a.data);
    setVersion((v) => v + 1);
  }

  async function open(id: number) {
    const a = await api.analysis(id);
    setCurrent(a.data);
  }

  const est = usage?.estimate_usd[model];
  const blocked = !usage || usage.analyzer === "none" || usage.analyses_today >= usage.daily_limit || (est ?? 0) > usage.remaining_usd;
  return (
    <div className="panel">
      <div className="row wrap">
        <h2>Claude-Chartanalyse</h2>
        <span className="row gap">
          <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Modell">
            {usage && Object.entries(usage.models).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
          <button onClick={() => void start()} disabled={blocked || pendingId !== null}>Mit Claude analysieren</button>
        </span>
      </div>
      {usage && (
        <p className="muted small-note">
          max. ca. {usd(est)} je Analyse · Monat: {usd(usage.spent_month_usd)} von {usd(usage.budget_month_usd)}
          {" "}(frei {usd(usage.remaining_usd)}) · heute {usage.analyses_today}/{usage.daily_limit}
          {usage.analyzer === "none" && " · API-Key fehlt: ./scripts/set-secret.sh anthropic_api_key"}
          {usage.analyzer === "fixture" && " · Test-Modus (kein API-Aufruf)"}
        </p>
      )}
      <p className="muted small-note">Gesendet werden der aktuelle Chart-Screenshot und Kurs-/Indikatordaten aus der Datenbank an die Anthropic API. Effort „high“, Ablehnungen werden serverseitig auf ein Ersatzmodell umgeleitet.</p>
      {msg && <p className="error">{msg}</p>}

      {current && <AnalysisView a={current} onAddLevel={onAddLevel} />}

      {history.length > 0 && (
        <details>
          <summary className="muted">Frühere Analysen ({history.length})</summary>
          <table>
            <thead><tr><th>Zeit</th><th>TF</th><th>Modell</th><th>Status</th><th>Konfidenz</th><th className="num">Kosten</th><th /></tr></thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id}>
                  <td>{new Date(h.created_at).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" })}</td>
                  <td>{h.tf === "1d" ? "1T" : "1W"}</td>
                  <td>{h.model.replace("claude-", "")}</td>
                  <td className={h.status === "done" ? "ok" : h.status === "failed" || h.status === "refused" ? "fail" : "muted"}>{STATUS[h.status] ?? h.status}</td>
                  <td>{h.confidence ? CONF[h.confidence] : "–"}</td>
                  <td className="num">{usd(h.cost_usd)}</td>
                  <td><button className="link" onClick={() => void open(h.id)}>Anzeigen</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

function AnalysisView({ a, onAddLevel }: { a: Analysis; onAddLevel: (price: number, kind: "support" | "resistance") => void }) {
  if (a.status !== "done" || !a.result) {
    return <p className={a.status === "failed" || a.status === "refused" ? "error" : "muted"}>{STATUS[a.status]}{a.error ? ` – ${a.error}` : ""}</p>;
  }
  const r = a.result;
  return (
    <div className="analysis">
      <div className="row wrap">
        <span>
          <span className={`trend-badge t-${r.trend.direction}`}>{TREND[r.trend.direction]} · {STRENGTH[r.trend.strength]}</span>
          {" "}<span className="muted small">Konfidenz {CONF[r.confidence]}</span>
        </span>
        <span className="muted small">
          {new Date(a.created_at).toLocaleString("de-DE")} · {(a.model_served ?? a.model).replace("claude-", "")}
          {a.model_served && a.model_served !== a.model && " (Fallback)"} · {usd(a.cost_usd)}
        </span>
      </div>
      <p>{r.summary}</p>
      <p className="muted">{r.trend.comment}</p>

      <div className="analysis-grid">
        <div>
          <h3>Key Levels</h3>
          <table>
            <tbody>
              {[...r.key_levels].sort((x, y) => y.price - x.price).map((l, i) => (
                <tr key={i}>
                  <td className={l.kind === "resistance" ? "fail" : "ok"}>{l.kind === "resistance" ? "Widerstand" : "Unterstützung"}</td>
                  <td className="num"><strong>{nf(l.price)}</strong></td>
                  <td className="muted small">{STRENGTH[l.strength]} · {l.reason}</td>
                  <td><button className="link" title="Als Linie in den Chart übernehmen" onClick={() => onAddLevel(l.price, l.kind)}>+ Linie</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h3>Momentum</h3>
          <p className="small"><strong>RSI:</strong> {r.momentum.rsi}</p>
          <p className="small"><strong>Divergenzen:</strong> {r.momentum.divergences}</p>
          <p className="small"><strong>Gleitende Durchschnitte:</strong> {r.momentum.moving_averages}</p>
          {r.patterns.length > 0 && <p className="small"><strong>Muster:</strong> {r.patterns.join(" · ")}</p>}
        </div>
      </div>

      <h3>Szenarien</h3>
      <div className="scenarios">
        {r.scenarios.map((s) => (
          <div key={s.name} className={`scenario s-${s.name}`}>
            <div className="row"><strong>{SCEN[s.name]}</strong><span>{s.probability_pct} %</span></div>
            <p className="small">{s.description}</p>
            <p className="small muted">Ziel {nf(s.target)} · Invalidierung {nf(s.invalidation)}</p>
          </div>
        ))}
      </div>
      {r.risks.length > 0 && <p className="small"><strong>Risiken:</strong> {r.risks.join(" · ")}</p>}
      <p className="muted small-note">Konfidenz: {r.confidence_reason} · KI-generiert, kann Fehler enthalten. Keine Anlageberatung.</p>
    </div>
  );
}
