"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type StockRow, type Strategy } from "./api";
import { big } from "./details";
import { CRIT_LABEL, nfmt, scoreClass } from "./scorecard";

type Col = { key: string; label: string; get: (r: StockRow) => number | string | null; fmt?: (r: StockRow) => string; num?: boolean };

const pct = (v: number | null) => (v === null ? "–" : `${nfmt(v)} %`);
const COLS: Col[] = [
  { key: "ranking_points", label: "Ranking", get: (r) => r.ranking_points, num: true },
  { key: "price", label: "Kurs", get: (r) => r.price, fmt: (r) => `${nfmt(r.price)} ${r.currency}`, num: true },
  { key: "country", label: "Land", get: (r) => r.country },
  { key: "industry", label: "Branche", get: (r) => r.industry },
  { key: "market_cap", label: "Marktkap.", get: (r) => r.market_cap, fmt: (r) => big(r.market_cap), num: true },
  { key: "dividend_yield", label: "Div.-Rendite", get: (r) => r.dividend_yield, fmt: (r) => pct(r.dividend_yield), num: true },
  { key: "dividend_cagr_5y", label: "Div.-Wachstum 5J.", get: (r) => r.dividend_cagr_5y, fmt: (r) => pct(r.dividend_cagr_5y), num: true },
  { key: "performance_5y", label: "Kursgewinn 5J.", get: (r) => r.performance_5y, fmt: (r) => pct(r.performance_5y), num: true },
  { key: "earnings_stability", label: "Stabilität Gewinn", get: (r) => r.earnings_stability, num: true },
  { key: "dividend_not_cut_years", label: "Div. nicht gesenkt seit", get: (r) => r.dividend_not_cut_years, fmt: (r) => (r.dividend_not_cut_years === null ? "–" : `${r.dividend_not_cut_years} J.`), num: true },
  { key: "payback_years", label: "Tilgung J.", get: (r) => (r.payback_years === "inf" ? 9999 : r.payback_years), fmt: (r) => nfmt(r.payback_years, 1), num: true },
  { key: "fair_value", label: "Fair Value", get: (r) => r.fair_value, num: true },
  { key: "discount", label: "Discount", get: (r) => r.discount, fmt: (r) => nfmt(r.discount, 1), num: true },
  { key: "fv_upside", label: "Abstand FV", get: (r) => r.fv_upside, fmt: (r) => pct(r.fv_upside), num: true },
  { key: "expected_return", label: "Rendite FV p.a.", get: (r) => r.expected_return, fmt: (r) => pct(r.expected_return), num: true },
];

export function Stocks({ onOpen }: { onOpen: (id: number) => void }) {
  const [rows, setRows] = useState<StockRow[] | null>(null);
  const [strategyName, setStrategyName] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "ranking_points", dir: -1 });
  const [editing, setEditing] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    void api.stocks().then((r) => {
      if (!active) return;
      setRows(r.data?.stocks ?? []);
      setStrategyName(r.data?.strategy ?? "");
    });
    return () => {
      active = false;
    };
  }, [version]);

  const sorted = useMemo(() => {
    const col = COLS.find((c) => c.key === sort.key);
    if (!rows || !col) return rows ?? [];
    return [...rows].sort((a, b) => {
      const x = col.get(a);
      const y = col.get(b);
      if (x === null) return 1;
      if (y === null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [rows, sort]);

  return (
    <div className="panel">
      <div className="row wrap">
        <h2>Aktienliste <span className="muted small">· Ranking-Strategie „{strategyName}“</span></h2>
        <button className="secondary small" onClick={() => setEditing((e) => !e)}>{editing ? "Schließen" : "Strategie bearbeiten"}</button>
      </div>
      {editing && <StrategyEditor onSaved={() => { setEditing(false); setVersion((v) => v + 1); }} />}
      {rows === null ? <p className="muted">Lade…</p> : rows.length === 0 ? (
        <p className="muted">Keine Aktien in der Watchlist (Typ „stock“).</p>
      ) : (
        <div className="table-scroll">
          <table className="stocks">
            <thead>
              <tr>
                <th>Aktie</th><th>Qualitäts-Scores</th>
                {COLS.map((c) => (
                  <th key={c.key} className={c.num ? "num sortable" : "sortable"} aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
                    onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? (s.dir === 1 ? -1 : 1) : -1 }))}>
                    {c.label}{sort.key === c.key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.id}>
                  <td><button className="link symbol" onClick={() => onOpen(r.id)}>{r.symbol}</button><div className="muted small">{r.name}</div></td>
                  <td>
                    <span className="badges" title="Dividendenertrag · Dividendenwachstum · Gewinnwachstum">
                      {(["dividend_yield", "dividend_growth", "earnings_growth"] as const).map((k) => (
                        <span key={k} className={`sb ${scoreClass(r.scores[k])}`}>{r.scores[k] ?? "–"}</span>
                      ))}
                    </span>
                    {r.fundamentals !== "success" && <div className="muted small">Fundamentaldaten: {r.fundamentals ?? "ausstehend"}</div>}
                  </td>
                  {COLS.map((c) => (
                    <td key={c.key} className={c.num ? "num" : ""}>
                      {c.key === "ranking_points" ? (
                        r.ranking_points === null ? "–" : <div className="achv small"><div style={{ width: `${r.ranking_points}%` }} /><span>{r.ranking_points}</span></div>
                      ) : c.fmt ? c.fmt(r) : nfmt(c.get(r) as number | string | null)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small-note">Scores nach docs/SCORING.md v0.2 (Aktienfinder-Stil). Fundamentaldaten: SEC EDGAR (US), sonst FMP. Keine Anlageberatung.</p>
    </div>
  );
}

const KEYS = ["earnings_stability", "earnings_growth_5y", "dividend_yield", "dividend_growth_5y", "dividend_stability", "max_payback_years", "min_discount"];

function StrategyEditor({ onSaved }: { onSaved: () => void }) {
  const [s, setS] = useState<Strategy | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    void api.strategy().then((r) => setS(r.data));
  }, []);
  if (!s) return null;
  const num = (v: string) => (v === "" ? 0 : Number(v.replace(",", ".")));
  return (
    <div className="strategy">
      <label>Name<input value={s.name} maxLength={60} onChange={(e) => setS({ ...s, name: e.target.value })} /></label>
      <table>
        <thead><tr><th>Kriterium</th><th className="num">Soll</th><th className="num">Gewicht (0–10)</th></tr></thead>
        <tbody>
          {KEYS.map((k) => (
            <tr key={k}>
              <td>{CRIT_LABEL[k]}</td>
              <td className="num"><input inputMode="decimal" value={String(s.targets[k] ?? "")} onChange={(e) => setS({ ...s, targets: { ...s.targets, [k]: num(e.target.value) } })} /></td>
              <td className="num"><input inputMode="decimal" value={String(s.weights[k] ?? 1)} onChange={(e) => setS({ ...s, weights: { ...s.weights, [k]: num(e.target.value) } })} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {err && <p className="error">{err}</p>}
      <button className="small" onClick={async () => {
        const r = await api.saveStrategy({ name: s.name, targets: s.targets, weights: s.weights });
        if (r.status === 200) onSaved(); else setErr(`Speichern fehlgeschlagen (${r.status})`);
      }}>Speichern</button>
    </div>
  );
}
