"use client";

import { ColorType, LineSeries, LineStyle, LineType, createChart, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { api, type FairValue, type FvLine, type FvMultiple } from "./api";
import { nfmt } from "./scorecard";

const PERIOD_LABEL: Record<string, string> = { "5": "5J", "8": "8J", "10": "10J", "15": "15J", "20": "20J", all: "Alle" };
const LINE_LABEL: Record<FvLine, string> = {
  earnings_adj: "Gewinn (bereinigt)", cashflow: "Cashflow", revenue: "Umsatz", dividend: "Dividende",
};
const LINE_MULT: Record<FvLine, FvMultiple> = { earnings_adj: "pe", cashflow: "pcf", revenue: "ps", dividend: "dy" };
const MULT_LABEL: Record<FvMultiple, string> = { pe: "Ø KGV", pcf: "Ø KCV", ps: "Ø KUV", dy: "Ø Div.-Rendite %" };
const MULTS: FvMultiple[] = ["pe", "pcf", "ps", "dy"];
const ts = (iso: string) => (Date.parse(`${iso}T00:00:00Z`) / 1000) as UTCTimestamp;
const pctS = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${nfmt(v)} %`);
const tone = (v: number | null | undefined) => ((v ?? 0) > 0 ? "ok" : (v ?? 0) < 0 ? "fail" : "muted");

export function FairValuePanel({ instrumentId, currency }: { instrumentId: number; currency: string }) {
  const [data, setData] = useState<FairValue | null>(null);
  const [period, setPeriod] = useState<string | null>(null);
  const [line, setLine] = useState<FvLine>("earnings_adj");
  const [draft, setDraft] = useState<Partial<Record<FvMultiple, string>>>({});
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void api.fairValue(instrumentId, period ?? undefined).then((r) => {
      if (!active || !r.data) return;
      setData(r.data);
      setDraft(Object.fromEntries(Object.entries(r.data.overrides).map(([k, v]) => [k, String(v)])));
    });
    return () => {
      active = false;
    };
  }, [instrumentId, period]);

  if (!data || !data.available) return null;

  const save = async (reset = false) => {
    const overrides: Partial<Record<FvMultiple, number>> = {};
    if (!reset) {
      for (const m of MULTS) {
        const raw = draft[m]?.trim().replace(",", ".");
        if (raw) overrides[m] = Number(raw);
      }
    }
    const r = await api.saveFairValue(instrumentId, { period: data.period, overrides });
    if (r.status === 200 && r.data) {
      setData(r.data);
      setPeriod(r.data.period);
      setDraft(Object.fromEntries(Object.entries(r.data.overrides).map(([k, v]) => [k, String(v)])));
      setMsg(reset ? "Ø-Werte zurückgesetzt" : "Gespeichert");
    } else {
      const detail = (r.data as unknown as { detail?: unknown } | null)?.detail;
      setMsg(`Fehler ${r.status}${typeof detail === "string" ? `: ${detail}` : ""}`);
    }
  };

  const cur = currency === "USD" ? "$" : currency;
  return (
    <div className="panel">
      <div className="row wrap">
        <h2>Fairer Wert <span className="muted small">· Standard, Ø über {PERIOD_LABEL[data.period]}</span></h2>
        <div className="seg">
          {data.periods.map((p) => (
            <button key={p} className={p === data.period ? "on" : ""} onClick={() => setPeriod(p)}>{PERIOD_LABEL[p]}</button>
          ))}
        </div>
      </div>

      <div className="kpis">
        <Kpi label="Kurs" value={`${nfmt(data.price)} ${cur}`} />
        <Kpi label="Fairer Wert (bereinigt)" value={`${nfmt(data.fv_std)} ${cur}`} />
        <Kpi label="Abstand zum FV" value={pctS(data.upside)} cls={tone(data.upside)} />
        <Kpi label={`Kauf-Limit (−${nfmt(data.margin_of_safety * 100, 0)} %)`} value={`${nfmt(data.buy_limit)} ${cur}`} />
        <Kpi label="Rendite Fairer Wert p.a." value={pctS(data.expected_return)} cls={tone(data.expected_return)} />
        <Kpi label="Dividendenrendite" value={data.dividend_yield === null ? "–" : `${nfmt(data.dividend_yield)} %`} />
      </div>

      <div className="row wrap">
        <div className="seg">
          {(Object.keys(LINE_LABEL) as FvLine[]).map((l) => (
            <button key={l} className={l === line ? "on" : ""} disabled={!data.history[l].length} onClick={() => setLine(l)}>
              {LINE_LABEL[l]}
            </button>
          ))}
        </div>
        <span className="muted small">FV {LINE_LABEL[line]}: <strong>{nfmt(data.fair_value[line])} {cur}</strong> · {MULT_LABEL[LINE_MULT[line]]} {nfmt(data.multiples[LINE_MULT[line]])}</span>
      </div>
      <FvChart data={data} line={line} />
      <p className="muted small-note">
        Linien ±10 %-Schritte um den fairen Wert (grün = unterbewertet, rot = überbewertet).
        {data.corridor && ` Prognosekorridor gestrichelt: Trend-Extrapolation des EPS (${nfmt(data.corridor.growth, 1)} % p.a.${data.corridor.capped ? `, begrenzt auf ${nfmt(data.corridor.growth_used, 0)} %` : ""}), keine Analystenschätzungen.`}
        {data.eps_basis === "diluted" && " „Bereinigt“ = verwässertes EPS (keine Daten zu Sondereffekten)."}
      </p>

      <h3>Ø-Multiples</h3>
      <div className="row gap">
        {MULTS.map((m) => (
          <label key={m} className="cfg">
            {MULT_LABEL[m]}
            <input
              inputMode="decimal"
              placeholder={data.medians[m] === null ? "–" : nfmt(data.medians[m])}
              value={draft[m] ?? ""}
              onChange={(e) => setDraft({ ...draft, [m]: e.target.value })}
            />
          </label>
        ))}
        <button className="small" onClick={() => void save()}>Speichern</button>
        <button className="secondary small" onClick={() => void save(true)}>Zurücksetzen</button>
        {msg && <span className="muted">{msg}</span>}
      </div>
      <p className="muted small-note">Leer = Median der täglichen Multiples (Platzhalter). Zeitraum und Werte werden je Aktie gespeichert; der Discount im Score nutzt diesen fairen Wert.</p>

      <YearTable data={data} />
      <Calculator data={data} cur={cur} />
    </div>
  );
}

function Kpi({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="kpi">
      <span className="muted small">{label}</span>
      <strong className={cls}>{value}</strong>
    </div>
  );
}

function FvChart({ data, line }: { data: FairValue; line: FvLine }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#181b22" }, textColor: "#c9ced8" },
      grid: { vertLines: { color: "#1f232b" }, horzLines: { color: "#1f232b" } },
      rightPriceScale: { borderColor: "#2a2f3a" },
      timeScale: { borderColor: "#2a2f3a" },
      localization: { priceFormatter: (p: number) => nfmt(p) },
    });
    const hist = data.history[line];
    if (hist.length) {
      const pts = hist.map((h) => ({ time: ts(h.date), value: h.value }));
      const last = pts[pts.length - 1]!;
      const end = ts(data.as_of);
      if (end > last.time) pts.push({ time: end, value: last.value });
      for (let k = -5; k <= 5; k++) {
        if (k === 0) continue;
        const s = chart.addSeries(LineSeries, {
          color: k < 0 ? `rgba(63,185,80,${0.15 + 0.08 * -k})` : `rgba(248,81,73,${0.15 + 0.08 * k})`,
          lineWidth: 1, lineType: LineType.WithSteps, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        s.setData(pts.map((p) => ({ time: p.time, value: p.value * (1 + k / 10) })));
      }
      const fvs = chart.addSeries(LineSeries, {
        color: "#f0b429", lineWidth: 2, lineType: LineType.WithSteps, priceLineVisible: false, title: "FV",
      });
      fvs.setData(pts);
    }
    if (line === "earnings_adj" && data.corridor) {
      const c = data.corridor;
      const s = chart.addSeries(LineSeries, {
        color: "#f0b429", lineWidth: 2, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false,
        title: "Prognose",
      });
      s.setData([{ time: ts(c.anchor.date), value: c.anchor.fair_value }, ...c.points.map((p) => ({ time: ts(p.date), value: p.fair_value }))]);
    }
    const price = chart.addSeries(LineSeries, { color: "#2f81f7", lineWidth: 2, title: "Kurs" });
    price.setData(data.prices.map(([d, v]) => ({ time: ts(d), value: v })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, line]);
  return <div ref={ref} className="fv-chart" />;
}

function YearTable({ data }: { data: FairValue }) {
  const rows = [...data.years].reverse().slice(0, 12);
  if (!rows.length) return null;
  const cols: [keyof FairValue["years"][number], string, "x" | "%" | "d"][] = [
    ["pe", "KGV", "x"], ["pcf", "KCV", "x"], ["ps", "KUV", "x"], ["dy", "Div.-Rendite", "%"],
    ["d_eps", "Δ Gewinn", "d"], ["d_ocf", "Δ Cashflow", "d"], ["d_rev", "Δ Umsatz", "d"], ["d_dps", "Δ Dividende", "d"],
  ];
  return (
    <>
      <h3>Kennzahlen je Geschäftsjahr <span className="muted small">· Multiples zum GJ-Ende</span></h3>
      <div className="table-scroll">
        <table>
          <thead><tr><th>GJ</th>{cols.map(([, l]) => <th key={l} className="num">{l}</th>)}</tr></thead>
          <tbody>
            {rows.map((y) => (
              <tr key={y.fiscal_year}>
                <td>{y.fiscal_year}</td>
                {cols.map(([k, l, t]) => {
                  const v = y[k] as number | null;
                  return (
                    <td key={l} className={`num ${t === "d" ? tone(v) : ""}`}>
                      {t === "d" ? pctS(v) : t === "%" ? (v === null ? "–" : `${nfmt(v)} %`) : nfmt(v, 1)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Calculator({ data, cur }: { data: FairValue; cur: string }) {
  const [amount, setAmount] = useState("1000");
  const price = data.price ?? 0;
  const years = 3;
  // Target: forecast corridor FV in 3 years if available, else today's FV_std.
  const target = data.corridor
    ? data.corridor.anchor.fair_value *
      (1 + data.corridor.growth_used / 100) ** ((Date.parse(data.as_of) - Date.parse(data.corridor.anchor.date)) / 31557600000 + years)
    : data.fv_std;
  const a = Number(amount.replace(",", ".")) || 0;
  const shares = price > 0 ? Math.floor(a / price) : 0;
  const invested = shares * price;
  const gain = target ? shares * (target - price) : null;
  const div = shares * (data.dps ?? 0) * years;
  const total = gain === null ? null : gain + div;
  const ret = total !== null && invested > 0 ? (total / invested) * 100 : null;
  const retPa = total !== null && invested > 0 ? ((1 + total / invested) ** (1 / years) - 1) * 100 : null;
  return (
    <>
      <h3>Renditerechner <span className="muted small">· Ziel: {data.corridor ? `Prognose-FV in ${years} J.` : "heutiger FV"} ({nfmt(target)} {cur})</span></h3>
      <div className="row gap">
        <label className="cfg">Betrag ({cur})<input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
        <span className="muted">= {shares} Aktien ({nfmt(invested)} {cur})</span>
      </div>
      <div className="kpis">
        <Kpi label="Kursgewinn" value={`${nfmt(gain)} ${cur}`} cls={tone(gain)} />
        <Kpi label={`Dividende (${years} J.)`} value={`${nfmt(div)} ${cur}`} />
        <Kpi label="Gesamt" value={`${nfmt(total)} ${cur}`} cls={tone(total)} />
        <Kpi label="Rendite" value={pctS(ret)} cls={tone(ret)} />
        <Kpi label="Rendite p.a." value={pctS(retPa)} cls={tone(retPa)} />
        <Kpi label="Persönl. Div.-Rendite" value={data.dps && price ? `${nfmt((data.dps / price) * 100)} %` : "–"} />
      </div>
      <p className="muted small-note">Annahme: Dividende konstant, keine Steuern/Gebühren. Keine Anlageberatung.</p>
    </>
  );
}
