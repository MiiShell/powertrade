"use client";

import { ColorType, LineSeries, LineStyle, createChart, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Counts, type Details as DetailsData, type Seasonality, type TaGroup, type Tf } from "./api";
import { ScorecardPanel } from "./scorecard";

const LABELS: Record<string, string> = {
  strong_buy: "Strong buy", buy: "Buy", neutral: "Neutral", sell: "Sell", strong_sell: "Strong sell",
};
const TF_LABEL: Record<Tf, string> = { "1d": "1 Tag", "1w": "1 Woche", "1mo": "1 Monat" };
const YEAR_COLORS = ["#f0b429", "#e3b341", "#56d4dd", "#3fb950", "#db61a2", "#a371f7", "#79c0ff", "#ffa657", "#7ee787"];
const MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];

const nf = (n: number | null | undefined, d = 2) =>
  n === null || n === undefined ? "–" : n.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (n: number | null | undefined) => (n === null || n === undefined ? "–" : `${n > 0 ? "+" : ""}${nf(n)} %`);
export function big(n: number | null | undefined) {
  if (n === null || n === undefined) return "–";
  const units: [number, string][] = [[1e12, " Bio."], [1e9, " Mrd."], [1e6, " Mio."], [1e3, " Tsd."]];
  for (const [v, u] of units) if (Math.abs(n) >= v) return nf(n / v, 2) + u;
  return nf(n, 2);
}
const cls = (n: number | null | undefined) => ((n ?? 0) > 0 ? "ok" : (n ?? 0) < 0 ? "fail" : "muted");

export function Details({ instrumentId }: { instrumentId: number }) {
  const [data, setData] = useState<DetailsData | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const [tf, setTf] = useState<Tf>("1d");
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void api.details(instrumentId).then((r) => {
      if (!active) return;
      setStatus(r.status);
      setData(r.status === 200 ? r.data : null);
    });
    return () => {
      active = false;
    };
  }, [instrumentId]);

  if (status !== null && status !== 200) return <div className="panel"><p className="error">Details nicht verfügbar ({status})</p></div>;
  if (!data) return <div className="panel"><p className="muted">Lade Details…</p></div>;

  const t = data.technicals[tf];
  const pv = data.pivots[tf];
  const canProfile = data.instrument.type === "stock" || data.instrument.type === "etf";

  return (
    <div className="details">
      <Header data={data} />

      {canProfile && (
        <div className="panel">
          <div className="row"><h2>Unternehmen</h2>
            <button className="secondary small" onClick={async () => {
              const r = await api.refreshProfile(instrumentId);
              setNote(r.data?.status ?? `Fehler ${r.status}`);
            }}>Profil aktualisieren (FMP)</button>
          </div>
          {note && <p className="muted">{note}</p>}
          <ProfileBlock data={data} />
        </div>
      )}

      {data.instrument.type === "stock" && <ScorecardPanel instrumentId={instrumentId} />}

      <div className="panel">
        <div className="row wrap">
          <h2>Technische Analyse</h2>
          <div className="seg">
            {(["1d", "1w", "1mo"] as Tf[]).map((x) => (
              <button key={x} className={tf === x ? "on" : ""} onClick={() => setTf(x)}>{TF_LABEL[x]}</button>
            ))}
          </div>
        </div>
        {t ? (
          <>
            <div className="gauges">
              <Gauge title="Oszillatoren" score={t.oscillators.score} label={t.oscillators.label} counts={t.oscillators.counts} />
              <Gauge title="Zusammenfassung" score={t.summary.score} label={t.summary.label} counts={t.summary.counts} large />
              <Gauge title="Gleitende Durchschnitte" score={t.moving_averages.score} label={t.moving_averages.label} counts={t.moving_averages.counts} />
            </div>
            <p className="muted small-note">Stand {t.as_of} · {t.bars} Kerzen · Regeln nach TradingView-Technical-Ratings (vereinfacht)</p>
            <div className="ta-tables">
              <TaTable title="Oszillatoren" group={t.oscillators} />
              <TaTable title="Gleitende Durchschnitte" group={t.moving_averages} />
            </div>
          </>
        ) : <p className="muted">Zu wenig Daten für {TF_LABEL[tf]}.</p>}
      </div>

      <div className="panel">
        <h2>Pivots {pv && <span className="muted small">· Basis: {pv.basis}</span>}</h2>
        {pv ? <PivotTable pv={pv.levels} /> : <p className="muted">Keine abgeschlossene Vorperiode.</p>}
      </div>

      <SeasonalPanel instrumentId={instrumentId} />
      <p className="muted small-note">Saisonalität und Ratings beruhen auf historischen Daten und sind keine Prognose oder Anlageberatung.</p>
    </div>
  );
}

export function Range({ label, lo, hi, value }: { label: string; lo: number; hi: number; value: number }) {
  const p = hi > lo ? Math.min(100, Math.max(0, ((value - lo) / (hi - lo)) * 100)) : 50;
  return (
    <div className="range">
      <div className="row"><span>{nf(lo)}</span><span className="muted">{label}</span><span>{nf(hi)}</span></div>
      <div className="bar"><div className="fill" style={{ left: 0, width: `${p}%` }} /><div className="marker" style={{ left: `${p}%` }} /></div>
    </div>
  );
}

function Header({ data }: { data: DetailsData }) {
  const s = data.stats as Partial<NonNullable<DetailsData["stats"]>> & DetailsData["stats"];
  const i = data.instrument;
  if (!("price" in s) || s.price === undefined) return <div className="panel"><h2>{i.symbol}</h2><p className="muted">Noch keine Kursdaten.</p></div>;
  const st = s as Required<typeof s> & { price: number; day_range: [number, number]; range_52w: [number, number] };
  const volPct = st.volume && st.avg_volume_30d ? Math.min(100, (st.volume / st.avg_volume_30d) * 100) : 0;
  return (
    <div className="panel header-card">
      <div className="hc-title"><strong className="sym">{i.symbol}</strong><span className="muted">{i.name}{i.exchange ? ` · ${i.exchange}` : ""} · {i.type} · {i.currency}</span></div>
      <div className="hc-price"><span className="price">{nf(st.price)}</span><span className="muted">{i.currency}</span></div>
      <div className={cls(st.change)}>{st.change !== null && st.change > 0 ? "+" : ""}{nf(st.change)} &nbsp;{pct(st.change_pct)} <span className="muted">· Stand {st.date}</span></div>
      <div className="hc-grid">
        <div className="range">
          <div className="row"><span className="muted">Volumen</span><span className="muted">Ø Volumen (30T)</span></div>
          <div className="row"><span>{big(st.volume)}</span><span>{big(st.avg_volume_30d)}</span></div>
          <div className="bar"><div className="fill vol" style={{ width: `${volPct}%` }} /></div>
        </div>
        <Range label="Tagesspanne" lo={st.day_range[0]} hi={st.day_range[1]} value={st.price} />
        <Range label="52-Wochen-Spanne" lo={st.range_52w[0]} hi={st.range_52w[1]} value={st.price} />
      </div>
      <div className="perf">
        {Object.entries(st.performance).map(([k, v]) => (
          <div key={k}><span className="muted">{k}</span><strong className={cls(v)}>{pct(v)}</strong></div>
        ))}
        <div><span className="muted">Allzeithoch</span><strong>{nf(st.all_time_high.price)}</strong><span className="muted small">{st.all_time_high.date}</span></div>
      </div>
    </div>
  );
}

function ProfileBlock({ data }: { data: DetailsData }) {
  const p = data.profile;
  if (!p) return <p className="muted">Noch kein Profil importiert (wird wöchentlich über FMP geladen, max. 5 pro Stunde).</p>;
  const rows: [string, string][] = [
    ["Name", p.company_name ?? "–"], ["Marktkapitalisierung", big(p.market_cap)], ["Sektor", p.sector ?? "–"],
    ["Branche", p.industry ?? "–"], ["Land", p.country ?? "–"], ["Börse", p.exchange ?? "–"],
    ["Mitarbeiter", p.employees?.toLocaleString("de-DE") ?? "–"], ["CEO", p.ceo ?? "–"], ["Beta", nf(p.beta)],
    ["Letzte Dividende", nf(p.last_dividend)], ["Ø Volumen", big(p.avg_volume)], ["IPO", p.ipo_date ?? "–"],
    ["ISIN", p.isin ?? "–"],
  ];
  return (
    <>
      <div className="kv">{rows.map(([k, v]) => <div key={k}><span className="muted">{k}</span><span>{v}</span></div>)}</div>
      {p.website && <p><a href={p.website} target="_blank" rel="noopener noreferrer nofollow">{p.website}</a></p>}
      {p.description && <details><summary>Beschreibung</summary><p className="desc">{p.description}</p></details>}
      <p className="muted small-note">Quelle: {p.source.toUpperCase()} · importiert {new Date(p.fetched_at).toLocaleString("de-DE")}</p>
    </>
  );
}

function Gauge({ title, score, label, counts, large }: { title: string; score: number | null; label: string; counts: Counts; large?: boolean }) {
  const w = large ? 260 : 200;
  const r = w / 2 - 14;
  const cx = w / 2;
  const cy = w / 2;
  const segs = ["#f85149", "#b62324", "#8b949e", "#2f81f7", "#79c0ff"];
  const arc = (a0: number, a1: number) => {
    const p = (a: number) => [cx + r * Math.cos(Math.PI - a), cy - r * Math.sin(Math.PI - a)];
    const [x0, y0] = p(a0);
    const [x1, y1] = p(a1);
    return `M ${x0} ${y0} A ${r} ${r} 0 0 1 ${x1} ${y1}`;
  };
  const angle = ((Math.max(-1, Math.min(1, score ?? 0)) + 1) / 2) * Math.PI; // 0 = left (sell)
  const nx = cx + (r - 18) * Math.cos(Math.PI - angle);
  const ny = cy - (r - 18) * Math.sin(Math.PI - angle);
  return (
    <div className="gauge">
      <svg viewBox={`0 0 ${w} ${w / 2 + 10}`} width={w} role="img" aria-label={`${title}: ${LABELS[label] ?? label}`}>
        {segs.map((c, i) => (
          <path key={c} d={arc((i * Math.PI) / 5 + 0.04, ((i + 1) * Math.PI) / 5 - 0.04)} stroke={c} strokeWidth={8} fill="none" strokeLinecap="round" />
        ))}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="#c9ced8" strokeWidth={4} strokeLinecap="round" />
        <circle cx={cx} cy={cy} r={6} fill="#c9ced8" />
      </svg>
      <div className="g-title">{title}</div>
      <div className={`g-label ${label.includes("buy") ? "buy" : label.includes("sell") ? "fail" : ""}`}>{LABELS[label] ?? label}</div>
      <div className="g-counts">
        <div><span className="muted">Sell</span><strong>{counts.sell}</strong></div>
        <div><span className="muted">Neutral</span><strong>{counts.neutral}</strong></div>
        <div><span className="muted">Buy</span><strong>{counts.buy}</strong></div>
      </div>
    </div>
  );
}

function TaTable({ title, group }: { title: string; group: TaGroup }) {
  return (
    <div>
      <h3>{title}</h3>
      <table>
        <thead><tr><th>Name</th><th className="num">Wert</th><th className="num">Signal</th></tr></thead>
        <tbody>
          {group.rows.map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td>
              <td className="num">{nf(r.value)}</td>
              <td className={`num ${r.action === "buy" ? "buy" : r.action === "sell" ? "fail" : "muted"}`}>
                {r.value === null ? "–" : r.action === "buy" ? "Buy" : r.action === "sell" ? "Sell" : "Neutral"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PivotTable({ pv }: { pv: NonNullable<DetailsData["pivots"]["1d"]>["levels"] }) {
  const cols = [["classic", "Classic"], ["fibonacci", "Fibonacci"], ["camarilla", "Camarilla"], ["woodie", "Woodie"], ["dm", "DM"]] as const;
  const levels = ["R3", "R2", "R1", "P", "S1", "S2", "S3"] as const;
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th>Pivot</th>{cols.map(([, l]) => <th key={l} className="num">{l}</th>)}</tr></thead>
        <tbody>
          {levels.map((lv) => (
            <tr key={lv}>
              <td className={lv.startsWith("R") ? "fail" : lv.startsWith("S") ? "ok" : ""}>{lv}</td>
              {cols.map(([k]) => <td key={k} className="num">{nf(pv[k][lv])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SeasonalPanel({ instrumentId }: { instrumentId: number }) {
  const [season, setSeason] = useState<Seasonality | null>(null);
  const [range, setRange] = useState<[number, number] | null>(null);
  const [showAvg, setShowAvg] = useState(true);
  const [view, setView] = useState<"chart" | "table">("chart");

  useEffect(() => {
    let active = true;
    const from = range?.[0] ?? new Date().getUTCFullYear() - 4; // default: last 5 years (like TradingView)
    void api.seasonality(instrumentId, from, range?.[1]).then((r) => {
      if (!active || !r.data) return;
      setSeason(r.data);
    });
    return () => {
      active = false;
    };
  }, [instrumentId, range]);

  const bounds = season?.range;
  const years = useMemo(() => (bounds ? Array.from({ length: bounds.max_year - bounds.min_year + 1 }, (_, k) => bounds.min_year + k) : []), [bounds]);

  return (
    <div className="panel">
      <div className="row wrap">
        <h2>Saisonalität</h2>
        <div className="row gap">
          <div className="seg">
            <button className={view === "chart" ? "on" : ""} onClick={() => setView("chart")}>Chart</button>
            <button className={view === "table" ? "on" : ""} onClick={() => setView("table")}>Tabelle</button>
          </div>
          <button className={showAvg ? "small" : "secondary small"} onClick={() => setShowAvg((v) => !v)}>Durchschnitt</button>
          {bounds && (
            <>
              <select aria-label="Von Jahr" value={bounds.from} onChange={(e) => setRange([Number(e.target.value), Math.max(Number(e.target.value), bounds.to)])}>
                {years.map((y) => <option key={y}>{y}</option>)}
              </select>
              <span className="muted">–</span>
              <select aria-label="Bis Jahr" value={bounds.to} onChange={(e) => setRange([Math.min(bounds.from, Number(e.target.value)), Number(e.target.value)])}>
                {years.map((y) => <option key={y}>{y}</option>)}
              </select>
            </>
          )}
        </div>
      </div>
      {!season ? <p className="muted">Lade…</p> : view === "chart" ? <SeasonChart season={season} showAvg={showAvg} /> : <SeasonTable season={season} />}
    </div>
  );
}

const DOY0 = Date.UTC(2000, 0, 1) / 1000; // leap year as x-axis canvas

function SeasonChart({ season, showAvg }: { season: Seasonality; showAvg: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const current = new Date().getUTCFullYear();
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#181b22" }, textColor: "#c9ced8" },
      grid: { vertLines: { color: "#1f232b" }, horzLines: { color: "#1f232b" } },
      rightPriceScale: { borderColor: "#2a2f3a" },
      timeScale: {
        borderColor: "#2a2f3a",
        tickMarkFormatter: (t: number) => MONTHS[new Date(t * 1000).getUTCMonth()] ?? "",
      },
      localization: {
        priceFormatter: (p: number) => `${nf(p)} %`,
        timeFormatter: (t: number) => new Date(t * 1000).toLocaleDateString("de-DE", { day: "2-digit", month: "short", timeZone: "UTC" }),
      },
      handleScroll: false,
      handleScale: false,
    });
    season.years.forEach((y, i) => {
      const isCur = y.year === current;
      const s = chart.addSeries(LineSeries, {
        color: isCur ? "#2f81f7" : YEAR_COLORS[i % YEAR_COLORS.length], lineWidth: isCur ? 3 : 1,
        priceLineVisible: false, title: String(y.year), crosshairMarkerVisible: false,
      });
      s.setData(y.points.map(([d, v]) => ({ time: (DOY0 + d * 86400) as UTCTimestamp, value: v })));
    });
    if (showAvg && season.average.length) {
      const s = chart.addSeries(LineSeries, { color: "#e6e8ee", lineWidth: 2, lineStyle: LineStyle.Dashed, priceLineVisible: false, title: "Ø" });
      s.setData(season.average.map(([d, v]) => ({ time: (DOY0 + d * 86400) as UTCTimestamp, value: v })));
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [season, showAvg, current]);
  return (
    <>
      <div ref={box} className="season-box" />
      <div className="legend-chips">
        {season.years.map((y, i) => (
          <span key={y.year} className="chip" style={{ borderColor: y.year === current ? "#2f81f7" : YEAR_COLORS[i % YEAR_COLORS.length] }}>
            {y.year} <strong className={cls(y.last)}>{pct(y.last)}</strong>
          </span>
        ))}
        {showAvg && season.average_years.length > 0 && <span className="chip muted">Ø aus {season.average_years.length} vollständigen Jahren</span>}
      </div>
    </>
  );
}

function SeasonTable({ season }: { season: Seasonality }) {
  const ys = Object.keys(season.monthly).sort().reverse();
  const heat = (v: number | undefined) => {
    if (v === undefined) return undefined;
    const a = Math.min(1, Math.abs(v) / 15) * 0.6 + 0.08;
    return { background: v >= 0 ? `rgba(63,185,80,${a})` : `rgba(248,81,73,${a})` };
  };
  return (
    <div className="table-scroll">
      <table className="heat">
        <thead><tr><th>Jahr</th>{MONTHS.map((m) => <th key={m} className="num">{m}</th>)}</tr></thead>
        <tbody>
          {ys.map((y) => (
            <tr key={y}><td>{y}</td>
              {MONTHS.map((_, m) => {
                const v = season.monthly[y]?.[String(m + 1)];
                return <td key={m} className="num" style={heat(v)}>{v === undefined ? "" : nf(v, 1)}</td>;
              })}
            </tr>
          ))}
          <tr className="sum"><td>Ø</td>{MONTHS.map((_, m) => <td key={m} className="num">{nf(season.monthly_stats[String(m + 1)]?.avg, 1)}</td>)}</tr>
          <tr className="sum"><td>% pos.</td>{MONTHS.map((_, m) => <td key={m} className="num">{nf(season.monthly_stats[String(m + 1)]?.positive_pct, 0)}</td>)}</tr>
        </tbody>
      </table>
    </div>
  );
}
