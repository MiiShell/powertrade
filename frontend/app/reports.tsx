"use client";

import { Fragment, type ReactNode, useEffect, useState } from "react";
import { api, type AiUsage, type Report, type ReportListItem, type WatchItem } from "./api";

const STATUS: Record<string, string> = {
  queued: "In Warteschlange…", running: "Claude recherchiert und schreibt… (ca. 2–6 Min.)", done: "Fertig",
  refused: "Abgelehnt", failed: "Fehlgeschlagen",
};
const nf = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "–" : v.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });
function big(v: number | null | undefined) {
  if (v === null || v === undefined) return "–";
  for (const [div, u] of [[1e12, " Bio."], [1e9, " Mrd."], [1e6, " Mio."]] as const) if (Math.abs(v) >= div) return nf(v / div, 1) + u;
  return nf(v, 2);
}
const usd = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${nf(v, v < 0.1 ? 3 : 2)} $`);

export function Reports({ instrumentId }: { instrumentId: number | null }) {
  const [items, setItems] = useState<WatchItem[]>([]);
  const [list, setList] = useState<ReportListItem[]>([]);
  const [meta, setMeta] = useState<{ cost_cap_usd: number; daily_limit: number } | null>(null);
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [model, setModel] = useState("claude-opus-5-5");
  const [current, setCurrent] = useState<Report | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    void api.watchlist().then((r) => active && setItems((r.data?.items ?? []).filter((i) => i.type === "stock")));
    void api.reports().then((r) => {
      if (!active || !r.data) return;
      setList(r.data.reports);
      setMeta({ cost_cap_usd: r.data.cost_cap_usd, daily_limit: r.data.daily_limit });
    });
    void api.aiUsage().then((r) => active && r.data && setUsage(r.data));
    return () => {
      active = false;
    };
  }, [version]);

  const pendingId = current && (current.status === "queued" || current.status === "running") ? current.id : null;
  useEffect(() => {
    if (pendingId === null) return;
    let active = true;
    const t = setInterval(() => {
      void api.report(pendingId).then((r) => {
        if (!active || !r.data) return;
        setCurrent(r.data);
        if (r.data.status !== "queued" && r.data.status !== "running") setVersion((v) => v + 1);
      });
    }, 4000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [pendingId]);

  async function create(iid: number) {
    setMsg(null);
    const r = await api.startReport(iid, model);
    if (r.status !== 202 || !r.data) {
      const d = (r.data as unknown as { detail?: unknown } | null)?.detail;
      setMsg(`Fehler ${r.status}${typeof d === "string" ? `: ${d}` : ""}`);
      return;
    }
    const rep = await api.report(r.data.id);
    setCurrent(rep.data);
    setVersion((v) => v + 1);
  }

  async function open(id: number) {
    const r = await api.report(id);
    setCurrent(r.data);
  }

  const blocked = !usage || usage.analyzer === "none" || (meta && (usage.reports_today >= meta.daily_limit || usage.remaining_usd < meta.cost_cap_usd));
  return (
    <>
      <div className="panel no-print">
        <h2>Claude Reports</h2>
        <form className="alert-form" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); void create(Number(f.get("instrument"))); }}>
          <label>Aktie
            <select name="instrument" defaultValue={instrumentId ?? undefined} key={`r${instrumentId}${items.length}`}>
              {items.map((i) => <option key={i.id} value={i.id}>{i.symbol} – {i.name}</option>)}
            </select>
          </label>
          <label>Modell
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {usage && Object.entries(usage.models).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <button type="submit" disabled={!!blocked || pendingId !== null || items.length === 0}>Bericht erstellen</button>
        </form>
        {usage && meta && (
          <p className="muted small-note">
            max. {usd(meta.cost_cap_usd)} je Bericht · KI-Budget Monat: {usd(usage.spent_month_usd)} von {usd(usage.budget_month_usd)}
            {" "}(frei {usd(usage.remaining_usd)}) · Berichte heute {usage.reports_today}/{meta.daily_limit}
            {usage.analyzer === "none" && " · API-Key fehlt: ./scripts/set-secret.sh anthropic_api_key"}
            {usage.analyzer === "fixture" && " · Test-Modus (kein API-Aufruf)"}
          </p>
        )}
        <p className="muted small-note">Zahlen stammen aus der PowerTrade-Datenbank (Tool-Aufrufe); Geschäftsmodell, Segmente und Ausblick recherchiert Claude per Websuche mit Quellen. Zahlen im Text, die nicht in den Datenbankwerten gefunden wurden, sind markiert.</p>
        {msg && <p className="error">{msg}</p>}
        {list.length > 0 && (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Zeit</th><th>Aktie</th><th>Version</th><th>Modell</th><th>Status</th><th className="num">Hinweise</th><th className="num">Kosten</th><th /></tr></thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.id} className={current?.id === r.id ? "unread" : ""}>
                    <td>{new Date(r.created_at).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" })}</td>
                    <td><strong>{r.symbol}</strong></td>
                    <td>v{r.version}</td>
                    <td>{r.model.replace("claude-", "")}</td>
                    <td className={r.status === "done" ? "ok" : r.status === "failed" || r.status === "refused" ? "fail" : "muted"} title={r.error ?? undefined}>{STATUS[r.status]}</td>
                    <td className="num">{r.warnings || "–"}</td>
                    <td className="num">{usd(r.cost_usd)}</td>
                    <td><button className="link" onClick={() => void open(r.id)}>Öffnen</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {current && <ReportView r={current} />}
    </>
  );
}

/** Minimal, safe rendering: paragraphs, **bold**, flagged numbers highlighted (no HTML injection). */
function Rich({ text, flagged }: { text: string; flagged: string[] }) {
  const paras = text.split(/\n{2,}/).filter((p) => p.trim());
  return (
    <>
      {paras.map((p, i) => <p key={i}>{inline(p, flagged)}</p>)}
    </>
  );
}

function inline(text: string, flagged: string[]): ReactNode[] {
  const out: ReactNode[] = [];
  text.split(/(\*\*[^*]+\*\*)/).forEach((part, i) => {
    const bold = part.startsWith("**") && part.endsWith("**");
    const body = bold ? part.slice(2, -2) : part;
    const marked = mark(body, flagged, i);
    out.push(bold ? <strong key={i}>{marked}</strong> : <Fragment key={i}>{marked}</Fragment>);
  });
  return out;
}

function mark(text: string, flagged: string[], key: number): ReactNode[] {
  const nums = flagged.map((f) => f.split(" ")[0] ?? "").filter((n) => n.length > 0);
  if (!nums.length) return [text];
  const esc = nums.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return text.split(new RegExp(`(${esc.join("|")})`)).map((t, j) =>
    nums.includes(t) ? <mark key={`${key}-${j}`} title="Nicht in den Datenbankwerten gefunden">{t}</mark> : t);
}

function List({ items, flagged }: { items: string[]; flagged: string[] }) {
  return <ul>{items.map((x, i) => <li key={i}>{inline(x, flagged)}</li>)}</ul>;
}

function ReportChart({ src, alt }: { src: string | undefined; alt: string }) {
  // Server-generated SVG as data URI: <img> keeps it out of any script context; next/image adds nothing here.
  // eslint-disable-next-line @next/next/no-img-element
  return src ? <img className="report-chart" src={src} alt={alt} /> : null;
}

function ReportView({ r }: { r: Report }) {
  if (r.status !== "done" || !r.sections) {
    return <div className="panel"><p className={r.status === "failed" || r.status === "refused" ? "error" : "muted"}>{r.symbol} v{r.version}: {STATUS[r.status]}{r.error ? ` – ${r.error}` : ""}</p></div>;
  }
  const s = r.sections;
  const snap = r.snapshot;
  const cur = snap.instrument.currency;
  const fl = (field: string) => (r.warnings ?? []).filter((w) => w.field === field).map((w) => w.number);
  const v = snap.valuation;
  return (
    <div className="panel report">
      <div className="row wrap no-print">
        <span className="muted small">{r.symbol} · Version {r.version} · {(r.stats?.model_served ?? r.model).replace("claude-", "")} · {usd(r.stats?.cost_usd)} · {r.stats?.web_searches ?? 0} Websuchen</span>
        <span className="row gap">
          <button className="secondary small" onClick={() => window.print()}>Drucken / PDF</button>
          <a className="button secondary small" href={`/api/reports/${r.id}/markdown`} download>Markdown</a>
        </span>
      </div>
      <h1>{s.title}</h1>
      <p className="muted small">{snap.instrument.name} ({snap.instrument.symbol}) · Datenstand {snap.as_of} · Version {r.version} · KI-generierter Bericht, keine Anlageberatung</p>

      <table className="kv">
        <tbody>
          <tr><td>Kurs</td><td>{nf(snap.market.price)} {cur}</td><td>Marktkapitalisierung</td><td>{big(snap.profile?.market_cap)} {cur}</td></tr>
          <tr><td>Fairer Wert (bereinigt)</td><td>{nf(v.fv_std)} {cur} ({nf(v.upside_pct)} %)</td><td>Ø KGV ({v.period_years} J.)</td><td>{nf(v.median_multiples?.pe, 1)}</td></tr>
          <tr><td>KBV aktuell / Median</td><td>{nf(v.pb_current, 1)} / {nf(v.pb_median_10y, 1)}</td><td>Dividendenrendite</td><td>{nf(v.dividend_yield_pct)} %</td></tr>
          <tr><td>Sektor / Branche</td><td colSpan={3}>{snap.profile?.sector ?? "–"} / {snap.profile?.industry ?? "–"}</td></tr>
        </tbody>
      </table>
      <Rich text={s.overview} flagged={fl("overview")} />

      <h2>Geschäftsmodell</h2><Rich text={s.business_model} flagged={fl("business_model")} />
      {s.segments.length > 0 && (<><h2>Segmente</h2><ul>{s.segments.map((g, i) => <li key={i}><strong>{g.name}:</strong> {g.description}</li>)}</ul></>)}
      <h2>Investment-These</h2><List items={s.investment_thesis} flagged={fl("investment_thesis")} />
      <h2>Kursentwicklung</h2><ReportChart src={r.charts["price_fv"]} alt="Kurs und fairer Wert" /><Rich text={s.price_history} flagged={fl("price_history")} />
      <h2>Operative Entwicklung & KPIs</h2><Rich text={s.operating_performance} flagged={fl("operating_performance")} />
      <AnnualTable r={r} />
      <h2>Ausblick / Guidance</h2><Rich text={s.guidance} flagged={fl("guidance")} />
      <h2>Umsatz, Gewinn & Margen</h2>
      <ReportChart src={r.charts["revenue_earnings"]} alt="Umsatz und Gewinn" /><ReportChart src={r.charts["margins"]} alt="Margen" /><ReportChart src={r.charts["per_share"]} alt="EPS und Dividende" />
      <Rich text={s.financials_comment} flagged={fl("financials_comment")} />
      <h2>Bilanz</h2><ReportChart src={r.charts["balance"]} alt="Bilanz" /><Rich text={s.balance_sheet} flagged={fl("balance_sheet")} />
      <h2>Kapitalallokation</h2><Rich text={s.capital_allocation} flagged={fl("capital_allocation")} />
      <h2>Bewertung</h2><Rich text={s.valuation} flagged={fl("valuation")} />
      <div className="analysis-grid">
        <div><h2>Chancen</h2><List items={s.opportunities} flagged={fl("opportunities")} /></div>
        <div><h2>Risiken</h2><List items={s.risks} flagged={fl("risks")} /></div>
      </div>
      <h2>Fazit</h2><Rich text={s.conclusion} flagged={fl("conclusion")} />

      <h2>Quellen</h2>
      <ul className="small">
        <li>Kennzahlen, Tabellen, Charts: PowerTrade-Datenbank (Fundamentaldaten {snap.sources_db?.fundamentals?.source?.toUpperCase() ?? "–"}, Kurse Yahoo/Stooq, Profil {snap.sources_db?.profile?.toUpperCase() ?? "–"})</li>
        {(r.sources ?? []).map((x, i) => (
          <li key={i}><a href={x.url} target="_blank" rel="noopener noreferrer nofollow">{x.title}</a> – {x.used_for}{!x.verified && <span className="fail"> (nicht aus der Websuche verifiziert)</span>}</li>
        ))}
      </ul>
      {(r.warnings ?? []).length > 0 && (
        <p className="muted small-note">Zahlenprüfung: {r.warnings!.length} Zahl(en) im Text wurden nicht in den Datenbankwerten gefunden und sind <mark>markiert</mark> (z. B. eigene Rundungen, Differenzen oder nicht gekennzeichnete externe Werte).</p>
      )}
      <p className="muted small-note">KI-generiert ({r.model}) und kann Fehler enthalten. Keine Anlageberatung.</p>
    </div>
  );
}

const COLS: [string, string, "big" | "num" | "pct"][] = [
  ["revenue", "Umsatz", "big"], ["net_income", "Nettogewinn", "big"], ["eps_diluted", "EPS", "num"],
  ["operating_margin_pct", "Op. Marge", "pct"], ["net_margin_pct", "Nettomarge", "pct"], ["free_cf", "Free Cashflow", "big"],
  ["dps", "Dividende", "num"], ["net_debt", "Nettoschulden", "big"], ["pb", "KBV", "num"],
];

function AnnualTable({ r }: { r: Report }) {
  const rows = r.snapshot.annual;
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th>GJ</th>{COLS.map(([, l]) => <th key={l} className="num">{l}</th>)}</tr></thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.fiscal_year as number}>
              <td>{a.fiscal_year as number}</td>
              {COLS.map(([k, , t]) => {
                const v = a[k] as number | null;
                return <td key={k} className="num">{t === "big" ? big(v) : t === "pct" ? (v === null ? "–" : `${nf(v, 1)} %`) : nf(v)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
