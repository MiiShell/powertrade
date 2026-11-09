"use client";

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ChartConfig, type ChartData, type PineScript, type FvSummary, type Stats, type WatchItem } from "./api";
import { BandFill, toRgba } from "./chart-fill";
import { Details, big } from "./details";
import { runPine, type PineBar, type PineResult } from "./pine-client";
import { PineEditor } from "./pine-editor";

const MA_COLORS = ["#f0b429", "#2f81f7", "#a371f7", "#3fb950", "#f778ba", "#79c0ff"];
const LEVEL_COLORS = ["#3fb950", "#f85149", "#2f81f7", "#f0b429"];
const DEFAULT_CFG: ChartConfig = { sma: [20, 50, 200], ema: [21], rsi: 14 };
const CFG_KEY = "pt.chart.cfg";
const WIDGETS_KEY = "pt.chart.widgets";
type Widgets = { rsi: boolean; pine: number[] };
const DEFAULT_WIDGETS: Widgets = { rsi: true, pine: [] };

function loadWidgets(): Widgets {
  try {
    const raw = window.localStorage.getItem(WIDGETS_KEY);
    if (raw) return { ...DEFAULT_WIDGETS, ...(JSON.parse(raw) as Partial<Widgets>) };
  } catch {
    /* storage unavailable */
  }
  return DEFAULT_WIDGETS;
}

type PineRun = { script: PineScript; result: PineResult };
const RANGES = [
  { label: "3M", days: 91 },
  { label: "6M", days: 182 },
  { label: "1J", days: 365 },
  { label: "5J", days: 1826 },
  { label: "Alle", days: 0 },
] as const;

const ts = (t: number) => t as UTCTimestamp;

function loadCfg(): ChartConfig {
  try {
    const raw = window.localStorage.getItem(CFG_KEY);
    if (raw) return { ...DEFAULT_CFG, ...(JSON.parse(raw) as Partial<ChartConfig>) };
  } catch {
    /* storage unavailable */
  }
  return DEFAULT_CFG;
}

function saveCfg(cfg: ChartConfig) {
  try {
    window.localStorage.setItem(CFG_KEY, JSON.stringify(cfg));
  } catch {
    /* ignore */
  }
}

function parsePeriods(s: string): number[] {
  return [...new Set(s.split(/[,\s]+/).map(Number).filter((n) => Number.isInteger(n) && n >= 2 && n <= 500))]
    .sort((a, b) => a - b)
    .slice(0, 6);
}

const fmt = (n: number | undefined | null, d = 2) =>
  n === undefined || n === null ? "–" : n.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });

type Legend = { o?: number; h?: number; l?: number; c?: number; values: Record<string, number | undefined> };

export function Chart({ instrumentId, view, onSelect, onView }: {
  instrumentId: number | null; view: "chart" | "details"; onSelect: (id: number) => void; onView: (v: "chart" | "details") => void;
}) {
  const [items, setItems] = useState<WatchItem[]>([]);
  const [tf, setTf] = useState<"1d" | "1w">("1d");
  const [cfg, setCfg] = useState<ChartConfig>(() => (typeof window === "undefined" ? DEFAULT_CFG : loadCfg()));
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [placing, setPlacing] = useState(false);
  const [levelColor, setLevelColor] = useState(LEVEL_COLORS[0] ?? "#3fb950");
  const [legend, setLegend] = useState<Legend | null>(null);
  const [version, setVersion] = useState(0);
  const [widgets, setWidgetsState] = useState<Widgets>(() => (typeof window === "undefined" ? DEFAULT_WIDGETS : loadWidgets()));
  const [scripts, setScripts] = useState<PineScript[]>([]);
  const [scriptsVersion, setScriptsVersion] = useState(0);
  const [pineRuns, setPineRuns] = useState<PineRun[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const [fvSum, setFvSum] = useState<FvSummary | null>(null);

  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const placingRef = useRef(placing);
  const colorRef = useRef(levelColor);
  useEffect(() => {
    placingRef.current = placing;
    colorRef.current = levelColor;
  }, [placing, levelColor]);

  useEffect(() => {
    void api.watchlist().then((r) => setItems(r.data?.items ?? []));
  }, []);

  useEffect(() => {
    void api.pineScripts().then((r) => setScripts(r.data?.scripts ?? []));
  }, [scriptsVersion]);

  const setWidgets = useCallback((w: Widgets) => {
    setWidgetsState(w);
    try {
      window.localStorage.setItem(WIDGETS_KEY, JSON.stringify(w));
    } catch {
      /* ignore */
    }
  }, []);

  const id = instrumentId ?? items[0]?.id ?? null;

  useEffect(() => {
    if (id === null) return;
    let active = true;
    void api.chart(id, tf, { ...cfg, rsi: widgets.rsi ? cfg.rsi : 0 }).then((r) => {
      if (!active) return;
      if (r.status === 200 && r.data) {
        setData(r.data);
        setError(null);
      } else setError(`Chart konnte nicht geladen werden (${r.status})`);
    });
    return () => {
      active = false;
    };
  }, [id, tf, cfg, version, widgets.rsi]);

  useEffect(() => {
    if (id === null) return;
    let active = true;
    void api.stats(id).then((r) => {
      if (active) setStats(r.status === 200 && r.data && "price" in r.data ? r.data : null);
    });
    void api.fairValueSummary(id).then((r) => {
      if (active) setFvSum(r.status === 200 ? r.data : null);
    });
    return () => {
      active = false;
    };
  }, [id, version]);

  const pineBars: PineBar[] = useMemo(
    () => (data ? data.bars.map(([t, o, h, l, c, v]) => ({ t, o, h, l, c, v })) : []),
    [data],
  );

  // Run enabled Pine scripts (sandboxed worker) whenever data or selection changes
  useEffect(() => {
    let active = true;
    const enabled = scripts.filter((s) => widgets.pine.includes(s.id));
    if (!data || enabled.length === 0) {
      void Promise.resolve().then(() => active && setPineRuns([]));
      return () => {
        active = false;
      };
    }
    void (async () => {
      const runs: PineRun[] = [];
      for (const script of enabled) runs.push({ script, result: await runPine(script.source, pineBars, data.tf) });
      if (active) setPineRuns(runs);
    })();
    return () => {
      active = false;
    };
  }, [data, pineBars, scripts, widgets.pine]);

  // Build chart whenever data changes
  useEffect(() => {
    const el = box.current;
    if (!el || !data) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#181b22" },
        textColor: "#c9ced8",
        panes: { separatorColor: "#2a2f3a" },
      },
      grid: { vertLines: { color: "#1f232b" }, horzLines: { color: "#1f232b" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#2a2f3a" },
      timeScale: { borderColor: "#2a2f3a", rightOffset: 5 },
      localization: {
        locale: "de-DE",
        priceFormatter: (p: number) => p.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: p < 1 ? 6 : 2 }),
      },
    });
    chartRef.current = chart;

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#3fb950", downColor: "#f85149", borderVisible: false, wickUpColor: "#3fb950", wickDownColor: "#f85149",
    });
    candles.setData(data.bars.map(([t, o, h, l, c]) => ({ time: ts(t), open: o, high: h, low: l, close: c })));
    candleRef.current = candles;

    const volume = chart.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(
      data.bars.filter((b) => b[5] !== null).map(([t, o, , , c, v]) => ({
        time: ts(t), value: v ?? 0, color: c >= o ? "rgba(63,185,80,.35)" : "rgba(248,81,73,.35)",
      })),
    );

    const lineSeries: Record<string, ISeriesApi<"Line">> = {};
    Object.entries(data.indicators).forEach(([name, pts], i) => {
      const s = chart.addSeries(LineSeries, {
        color: MA_COLORS[i % MA_COLORS.length], lineWidth: name.startsWith("ema") ? 1 : 2,
        lineStyle: name.startsWith("ema") ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, title: "",
      });
      s.setData(pts.map(([t, v]) => ({ time: ts(t), value: v })));
      lineSeries[name] = s;
    });

    for (const lv of data.levels) {
      candles.createPriceLine({ price: lv.price, color: lv.color, lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: lv.label });
    }

    if (data.rsi) {
      const rsi = chart.addSeries(LineSeries, { color: "#a371f7", lineWidth: 1, priceLineVisible: false, title: `RSI ${data.rsi.period}` }, 1);
      rsi.setData(data.rsi.values.map(([t, v]) => ({ time: ts(t), value: v })));
      for (const [p, c] of [[70, "#f85149"], [50, "#4b5263"], [30, "#3fb950"]] as const) {
        rsi.createPriceLine({ price: p, color: c, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
      }
      const divs = data.rsi.divergences.slice(-40);
      for (const d of divs) {
        const color = d.kind === "bull" ? "#3fb950" : "#f85149";
        const seg = chart.addSeries(LineSeries, { color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, 1);
        seg.setData([{ time: ts(d.prev_t), value: d.prev_rsi }, { time: ts(d.t), value: d.rsi }]);
      }
      const markers: SeriesMarker<Time>[] = divs.map((d) => ({
        time: ts(d.t),
        position: d.kind === "bull" ? "belowBar" : "aboveBar",
        shape: d.kind === "bull" ? "arrowUp" : "arrowDown",
        color: d.kind === "bull" ? "#3fb950" : "#f85149",
        text: d.kind === "bull" ? "BULL" : "BEAR",
      }));
      createSeriesMarkers(rsi, markers);
      chart.panes()[1]?.setStretchFactor(0.35);
      chart.panes()[0]?.setStretchFactor(1);
    }

    // ---- Pine indicators ----
    let nextPane = data.rsi ? 2 : 1;
    for (const { result } of pineRuns) {
      if (!result.ok) continue;
      const pane = result.overlay ? 0 : nextPane++;
      const byTitle = new Map<string, [number, number][]>();
      let anchor: ISeriesApi<"Line"> | ISeriesApi<"Candlestick"> | null = pane === 0 ? candles : null;
      for (const pl of result.plots) {
        if (pl.kind !== "line") continue;
        byTitle.set(pl.title, pl.data.map(([t, v]) => [t, v]));
        if (pl.hidden) continue;
        const s = chart.addSeries(LineSeries, {
          color: toRgba(pl.color), lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
          crosshairMarkerVisible: false, title: "",
        }, pane);
        s.setData(pl.data.map(([t, v, c]) => (c ? { time: ts(t), value: v, color: toRgba(c) } : { time: ts(t), value: v })));
        anchor ??= s;
      }
      if (!anchor) {
        // pane with only hlines/fills: invisible helper series spanning the data range
        anchor = chart.addSeries(LineSeries, { visible: false, priceLineVisible: false, lastValueVisible: false }, pane);
        anchor.setData(data.bars.map(([t]) => ({ time: ts(t), value: 50 })));
      }
      for (const pl of result.plots) {
        if (pl.kind === "hline") {
          anchor.createPriceLine({ price: pl.value, color: toRgba(pl.color), lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
        } else if (pl.kind === "fill") {
          const a = byTitle.get(pl.plot1);
          const b = byTitle.get(pl.plot2);
          if (a && b) anchor.attachPrimitive(new BandFill(a, b, toRgba(pl.color)));
        }
      }
      if (pane > 0) chart.panes()[pane]?.setStretchFactor(0.35);
    }

    const onMove = (p: MouseEventParams<Time>) => {
      const bar = p.seriesData.get(candles) as { open: number; high: number; low: number; close: number } | undefined;
      if (!bar) return setLegend(null);
      const values: Record<string, number | undefined> = {};
      for (const [name, s] of Object.entries(lineSeries)) values[name] = (p.seriesData.get(s) as { value?: number } | undefined)?.value;
      setLegend({ o: bar.open, h: bar.high, l: bar.low, c: bar.close, values });
    };
    const onClick = (p: MouseEventParams<Time>) => {
      if (!placingRef.current || !p.point) return;
      const price = candles.coordinateToPrice(p.point.y);
      if (price === null || price <= 0) return;
      setPlacing(false);
      void api.addLevel(data.instrument.id, Math.round(price * 100) / 100, colorRef.current).then(() => setVersion((v) => v + 1));
    };
    chart.subscribeCrosshairMove(onMove);
    chart.subscribeClick(onClick);
    requestAnimationFrame(() => showRange(chart, data, 365));

    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.unsubscribeClick(onClick);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
    };
  }, [data, view, pineRuns]);

  const applyCfg = useCallback((next: ChartConfig) => {
    setCfg(next);
    saveCfg(next);
  }, []);

  const last = data?.bars.at(-1);
  const prev = data?.bars.at(-2);
  const change = last && prev ? (last[4] / prev[4] - 1) * 100 : null;
  const maNames = useMemo(() => Object.keys(data?.indicators ?? {}), [data]);

  return (
    <div className="panel chart-panel">
      <div className="chart-toolbar">
        <div className="seg">
          <button className={view === "chart" ? "on" : ""} onClick={() => onView("chart")}>Chart</button>
          <button className={view === "details" ? "on" : ""} onClick={() => onView("details")}>Details</button>
        </div>
        <select value={id ?? ""} onChange={(e) => onSelect(Number(e.target.value))} aria-label="Instrument">
          {items.map((i) => <option key={i.id} value={i.id}>{i.symbol} – {i.name}</option>)}
        </select>
        {view === "chart" && (<>
        <div className="seg">
          {(["1d", "1w"] as const).map((t) => (
            <button key={t} className={tf === t ? "on" : ""} onClick={() => setTf(t)}>{t === "1d" ? "1T" : "1W"}</button>
          ))}
        </div>
        <div className="seg">
          {RANGES.map((r) => (
            <button key={r.label} onClick={() => chartRef.current && data && showRange(chartRef.current, data, r.days)}>{r.label}</button>
          ))}
        </div>
        <div className="menu-wrap">
          <button className="secondary small" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>Indikatoren ▾</button>
          {menuOpen && (
            <div className="menu" role="menu">
              <label className="menu-item">
                <input type="checkbox" checked={widgets.rsi} onChange={(e) => setWidgets({ ...widgets, rsi: e.target.checked })} />
                RSI + Divergenzen <span className="badge">built-in</span>
              </label>
              <div className="menu-sep">Pine Scripts</div>
              {scripts.map((s) => (
                <label key={s.id} className="menu-item">
                  <input type="checkbox" checked={widgets.pine.includes(s.id)} onChange={(e) => setWidgets({
                    ...widgets, pine: e.target.checked ? [...widgets.pine, s.id] : widgets.pine.filter((x) => x !== s.id),
                  })} />
                  {s.name}
                </label>
              ))}
              <button className="small" onClick={() => { setEditorOpen(true); setMenuOpen(false); }}>✎ Pine-Editor</button>
            </div>
          )}
        </div>
        <button className="secondary small" title="Neues Pine Script" onClick={() => setEditorOpen(true)}>✎ Pine</button>
        <label className="cfg">SMA<input defaultValue={cfg.sma.join(",")} key={`s${cfg.sma.join()}`} onBlur={(e) => applyCfg({ ...cfg, sma: parsePeriods(e.target.value) })} /></label>
        <label className="cfg">EMA<input defaultValue={cfg.ema.join(",")} key={`e${cfg.ema.join()}`} onBlur={(e) => applyCfg({ ...cfg, ema: parsePeriods(e.target.value) })} /></label>
        <label className="cfg">RSI<input defaultValue={cfg.rsi || ""} key={`r${cfg.rsi}`} size={3} onBlur={(e) => {
          const n = Number(e.target.value);
          applyCfg({ ...cfg, rsi: Number.isInteger(n) && n >= 2 && n <= 100 ? n : 0 });
        }} /></label>
        </>)}
      </div>

      {view === "details" && id !== null && <Details instrumentId={id} />}
      {view === "chart" && (<>
      {stats && (
        <div className="widgets">
          <div className="widget">
            <div className="row"><span className="muted">Kurs</span><span className={(stats.change_pct ?? 0) >= 0 ? "ok" : "fail"}>{fmt(stats.change_pct)} %</span></div>
            <strong className="w-price">{fmt(stats.price)}</strong>
            <span className="muted small">Vol. {big(stats.volume)} · Ø30T {big(stats.avg_volume_30d)}</span>
          </div>
          <WidgetRange label="Tagesspanne" lo={stats.day_range[0]} hi={stats.day_range[1]} value={stats.price} />
          <WidgetRange label="Wochenspanne" lo={stats.range_week[0]} hi={stats.range_week[1]} value={stats.price} />
          <WidgetRange label="52-Wochen-Spanne" lo={stats.range_52w[0]} hi={stats.range_52w[1]} value={stats.price} />
          {fvSum?.available && <WidgetFairValue fv={fvSum} price={stats.price} onOpen={() => onView("details")} />}
        </div>
      )}
      {pineRuns.filter((r) => !r.result.ok).map((r) => (
        <p key={r.script.id} className="error">Pine „{r.script.name}“: {(r.result as { error: string }).error}</p>
      ))}
      {data && (
        <div className="chart-legend">
          <strong>{data.instrument.symbol}</strong>
          <span className="muted">{data.instrument.name} · {data.instrument.currency}</span>
          {legend ? (
            <span>O {fmt(legend.o)} H {fmt(legend.h)} L {fmt(legend.l)} C {fmt(legend.c)}</span>
          ) : (
            last && <span>{fmt(last[4])} <span className={(change ?? 0) >= 0 ? "ok" : "fail"}>{fmt(change)} %</span></span>
          )}
          {pineRuns.filter((r) => r.result.ok).map((r) => (
            <span key={`p${r.script.id}`} className="pine-chip">{r.script.name}
              <button className="link" aria-label="Indikator ausblenden" onClick={() => setWidgets({ ...widgets, pine: widgets.pine.filter((x) => x !== r.script.id) })}>✕</button>
            </span>
          ))}
          {maNames.map((n, i) => (
            <span key={n} style={{ color: MA_COLORS[i % MA_COLORS.length] }}>
              {n.toUpperCase()} {fmt(legend?.values[n] ?? data.indicators[n]?.at(-1)?.[1])}
            </span>
          ))}
        </div>
      )}

      {error && <p className="error">{error}</p>}
      <div ref={box} className={`chart-box${placing ? " placing" : ""}`} />

      <div className="levels">
        <span className="muted">Linien:</span>
        {data?.levels.map((lv) => (
          <span key={lv.id} className="level-chip" style={{ borderColor: lv.color }}>
            {fmt(lv.price)}
            <button className="link" aria-label="Linie löschen" onClick={() => void api.deleteLevel(data.instrument.id, lv.id).then(() => setVersion((v) => v + 1))}>✕</button>
          </span>
        ))}
        <span className="colors">
          {LEVEL_COLORS.map((c) => (
            <button key={c} aria-label={`Farbe ${c}`} className={c === levelColor ? "dot on" : "dot"} style={{ background: c }} onClick={() => setLevelColor(c)} />
          ))}
        </span>
        <button className={placing ? "small" : "secondary small"} onClick={() => setPlacing((p) => !p)}>
          {placing ? "Klick in den Chart…" : "+ Linie"}
        </button>
      </div>
      <p className="muted small-note">Charts: TradingView Lightweight Charts™. Pine Scripts: PineTS (AGPL-3.0). Keine Anlageberatung.</p>
      </>)}
      {editorOpen && data && (
        <PineEditor bars={pineBars} tf={data.tf} onClose={() => setEditorOpen(false)} onSaved={(sid) => {
          setScriptsVersion((v) => v + 1);
          if (!widgets.pine.includes(sid)) setWidgets({ ...widgets, pine: [...widgets.pine, sid] });
        }} />
      )}
    </div>
  );
}

function WidgetFairValue({ fv, price, onOpen }: { fv: Extract<FvSummary, { available: true }>; price: number; onOpen: () => void }) {
  // Position of the price within the valuation bands FV -50 % .. FV +50 % (green = below FV, red = above).
  const lo = fv.fv_std * 0.5;
  const hi = fv.fv_std * 1.5;
  const p = Math.min(100, Math.max(0, ((price - lo) / (hi - lo)) * 100));
  const up = fv.upside ?? 0;
  return (
    <button className="widget widget-btn" title="Details: Fairer Wert" onClick={onOpen}>
      <div className="row"><span className="muted">Fairer Wert ({fv.period === "all" ? "Alle" : `${fv.period}J`})</span>
        <span className={up >= 0 ? "ok" : "fail"}>{up > 0 ? "+" : ""}{fmt(fv.upside)} %</span></div>
      <strong className="w-price">{fmt(fv.fv_std)}</strong>
      <div className="range"><div className="bar fv-bar"><div className="marker" style={{ left: `${p}%` }} /></div></div>
      <span className="muted small">Kauf-Limit {fmt(fv.buy_limit)} · Rendite p.a. {fmt(fv.expected_return)} %</span>
    </button>
  );
}

function WidgetRange({ label, lo, hi, value }: { label: string; lo: number; hi: number; value: number }) {
  const p = hi > lo ? Math.min(100, Math.max(0, ((value - lo) / (hi - lo)) * 100)) : 50;
  return (
    <div className="widget">
      <span className="muted">{label}</span>
      <div className="row w-range"><span>{fmt(lo)}</span><span>{fmt(hi)}</span></div>
      <div className="range"><div className="bar"><div className="fill" style={{ width: `${p}%` }} /><div className="marker" style={{ left: `${p}%` }} /></div></div>
    </div>
  );
}

function showRange(chart: IChartApi, data: ChartData, days: number) {
  const lastT = data.bars.at(-1)?.[0];
  const firstT = data.bars[0]?.[0];
  if (lastT === undefined || firstT === undefined) return;
  if (days === 0) return chart.timeScale().fitContent();
  chart.timeScale().setVisibleRange({ from: ts(Math.max(firstT, lastT - days * 86400)), to: ts(lastT) });
}
