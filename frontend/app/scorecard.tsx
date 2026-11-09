"use client";

import { useEffect, useState } from "react";
import { api, type Criterion, type Scorecard as ScorecardData } from "./api";

export const PROFILE_LABEL: Record<string, string> = {
  dividend_yield: "Dividendenertrag", dividend_growth: "Dividendenwachstum", earnings_growth: "Gewinnwachstum",
};
export const CRIT_LABEL: Record<string, string> = {
  earnings_stability: "Gewinnstabilität", earnings_growth_10y: "Gewinnwachstum (10J.)", payback_years: "Max. Tilgungsjahre",
  momentum: "Momentum", discount: "Discount", dividend_yield: "Dividendenrendite", dividend_stability: "Dividendenstabilität",
  dividend_growth_10y: "Dividendenwachstum (10J.)", earnings_growth_5y: "Zuwachs Gewinn 5J.", dividend_growth_5y: "Zuwachs Dividende 5J.",
  max_payback_years: "Max. Tilgung Jahre", min_discount: "Min. Discount",
};
const PCT = new Set(["earnings_growth_10y", "earnings_growth_5y", "momentum", "dividend_yield", "dividend_growth_10y", "dividend_growth_5y"]);
const PROFILE_COLOR: Record<string, string> = { dividend_yield: "#1f6feb", dividend_growth: "#56a3e8", earnings_growth: "#8ec641" };

export const nfmt = (v: number | string | null | undefined, d = 2) =>
  v === null || v === undefined ? "–" : v === "inf" ? "∞" : typeof v === "number" ? v.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d }) : String(v);

export function scoreClass(s: number | null | undefined) {
  if (s === null || s === undefined) return "sc-na";
  return s >= 7 ? "sc-hi" : s >= 4 ? "sc-mid" : "sc-lo";
}

function scaleText(c: Criterion) {
  if (c.criterion === "payback_years") return "∞ → 2";
  if (!c.scale) return "";
  const u = PCT.has(c.criterion) ? " %" : "";
  return `${c.scale[0]}${u} → ${c.scale[1]}${u}`;
}

function Bars({ points, color }: { points: number | null; color: string }) {
  const filled = points === null ? 0 : Math.round(points);
  return (
    <div className="segbar" aria-label={points === null ? "n/a" : `${nfmt(points, 1)} von 10`}>
      {Array.from({ length: 10 }, (_, i) => <span key={i} style={{ background: i < filled ? color : undefined }} />)}
    </div>
  );
}

export function ScorecardPanel({ instrumentId }: { instrumentId: number }) {
  const [card, setCard] = useState<ScorecardData | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void api.scorecard(instrumentId).then((r) => active && setCard(r.data));
    return () => {
      active = false;
    };
  }, [instrumentId]);

  if (!card) return null;
  const refresh = async () => {
    const r = await api.refreshFundamentals(instrumentId);
    setNote(r.data?.status ?? `Fehler ${r.status}`);
  };
  const notes = (card.metrics.notes as string[] | undefined) ?? [];

  return (
    <>
      <div className="panel">
        <div className="row wrap">
          <h2>Scorecard</h2>
          <button className="secondary small" onClick={refresh}>Fundamentaldaten aktualisieren</button>
        </div>
        {note && <p className="muted">{note}</p>}
        {!card.profiles ? (
          <p className="muted">Noch keine Fundamentaldaten{card.run ? ` (letzter Import: ${card.run.status}${card.run.error ? ` – ${card.run.error}` : ""})` : " – Import läuft wöchentlich bzw. auf Knopfdruck"}.</p>
        ) : (
          <>
            <div className="profiles">
              {(["dividend_yield", "dividend_growth", "earnings_growth"] as const).map((k) => {
                const p = card.profiles![k];
                return (
                  <div key={k} className="profile" style={{ borderTopColor: PROFILE_COLOR[k] }}>
                    <h3 style={{ color: PROFILE_COLOR[k] }}>{PROFILE_LABEL[k]}</h3>
                    {p.score === null ? <p className="muted">{p.reason ?? "n/a"}</p> : p.criteria.map((c) => (
                      <div key={c.criterion} className="crit">
                        <div className="row"><span>{CRIT_LABEL[c.criterion]}{c.warn && <span className="fail"> !</span>}</span>
                          <span className="muted">{nfmt(c.value)}{PCT.has(c.criterion) && typeof c.value === "number" ? " %" : ""}</span></div>
                        <Bars points={c.points} color={PROFILE_COLOR[k] ?? "#2f81f7"} />
                        <div className="row muted small"><span>{scaleText(c).split(" → ")[0]}</span><span>{scaleText(c).split(" → ")[1]}</span></div>
                      </div>
                    ))}
                    <div className="qs">Qualitäts-Score <strong className={scoreClass(p.score)}>{p.score ?? "–"}</strong></div>
                  </div>
                );
              })}
            </div>
            <p className="muted small-note">
              Fair Value (bereinigt): {nfmt(card.metrics.fair_value as number | null)} · Ø KGV {nfmt(card.metrics.median_pe as number | null, 1)} · {card.metrics.eps_years as number} Geschäftsjahre
              {card.run && ` · Quelle ${card.run.source?.toUpperCase() ?? "–"}, Import ${new Date(card.run.finished_at).toLocaleDateString("de-DE")}`}
              {notes.length > 0 && ` · Hinweis: ${notes.join("; ")}`}
            </p>
          </>
        )}
      </div>

      {card.ranking && (
        <div className="panel">
          <h2>Ranking <span className="muted small">· Strategie „{card.strategy.name}“</span></h2>
          <div className="rank-points">Punkte: <strong className={scoreClass(card.ranking.points / 10)}>{card.ranking.points}</strong> von 100</div>
          <table>
            <thead><tr><th>Kriterium</th><th className="num">Soll</th><th className="num">Ist</th><th>Zielerreichung</th></tr></thead>
            <tbody>
              {card.ranking.criteria.map((r) => (
                <tr key={r.criterion}>
                  <td>{CRIT_LABEL[r.criterion]}</td>
                  <td className="num">{nfmt(r.target)}</td>
                  <td className="num">{nfmt(r.actual)}</td>
                  <td><div className="achv"><div style={{ width: `${r.achievement}%` }} /><span>{nfmt(r.achievement, 0)} %</span></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(card.fundamentals).length > 0 && <FundamentalsTable data={card.fundamentals} />}
    </>
  );
}

const F_ROWS: [string, string, number][] = [
  ["revenue", "Umsatz", 0], ["net_income", "Nettogewinn", 0], ["eps_diluted", "EPS (verwässert)", 2], ["dps", "Dividende je Aktie", 2],
  ["operating_cf", "Operativer Cashflow", 0], ["free_cf", "Free Cashflow", 0], ["debt", "Finanzschulden", 0], ["cash", "Cash", 0],
  ["equity", "Eigenkapital", 0],
];

function FundamentalsTable({ data }: { data: Record<string, [number, number][]> }) {
  const years = [...new Set(Object.values(data).flatMap((s) => s.map(([y]) => y)))].sort((a, b) => b - a).slice(0, 10);
  const big = (v: number | undefined, d: number) => {
    if (v === undefined) return "";
    if (d > 0) return nfmt(v, d);
    const a = Math.abs(v);
    return a >= 1e9 ? `${nfmt(v / 1e9, 1)} Mrd.` : a >= 1e6 ? `${nfmt(v / 1e6, 1)} Mio.` : nfmt(v, 0);
  };
  return (
    <div className="panel">
      <h2>Fundamentaldaten <span className="muted small">· Geschäftsjahre, je Aktie split-bereinigt</span></h2>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Kennzahl</th>{years.map((y) => <th key={y} className="num">{y}</th>)}</tr></thead>
          <tbody>
            {F_ROWS.filter(([k]) => data[k]).map(([k, label, d]) => {
              const m = new Map(data[k]);
              return <tr key={k}><td>{label}</td>{years.map((y) => <td key={y} className="num">{big(m.get(y), d)}</td>)}</tr>;
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
