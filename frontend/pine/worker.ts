/// <reference lib="webworker" />
// Sandboxed Pine Script runtime (PineTS, AGPL-3.0). Runs in a dedicated Web Worker served with its own CSP
// ('unsafe-eval' only here, no network: connect-src 'none'). The main page CSP stays strict.
import { PineTS } from "pinets";

type Bar = { t: number; o: number; h: number; l: number; c: number; v: number | null };
type Req = { id: number; source: string; bars: Bar[]; tf: "1d" | "1w" };
type Plot =
  | { kind: "line"; title: string; overlay: boolean; hidden: boolean; color: string; data: [number, number, string | null][] }
  | { kind: "hline"; title: string; value: number; color: string }
  | { kind: "fill"; title: string; plot1: string; plot2: string; color: string };

const ctx = self as unknown as DedicatedWorkerGlobalScope;
const DAY = 86_400_000;

ctx.onmessage = async (e: MessageEvent<Req>) => {
  const { id, source, bars, tf } = e.data;
  try {
    const span = tf === "1w" ? 7 * DAY : DAY;
    const klines = bars.map((b) => ({
      openTime: b.t * 1000, open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v ?? 0,
      closeTime: b.t * 1000 + span - 1,
    }));
    const pine = new PineTS(klines as never, "POWERTRADE", tf === "1w" ? "1W" : "1D");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const run: any = await pine.run(source);
    const plots: Plot[] = [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    for (const [key, pl] of Object.entries<any>(run.plots ?? {})) {
      if (key.startsWith("__")) continue;
      const o = pl.options ?? {};
      const title = pl.title ?? key;
      if (o.style === "fill") {
        plots.push({ kind: "fill", title, plot1: String(o.plot1), plot2: String(o.plot2), color: o.color ?? "#2f81f733" });
        continue;
      }
      const pts = (pl.data ?? []) as { time: number; value: number | null; title?: string; options?: { color?: string } }[];
      if (o.style === "hline") {
        const last = [...pts].reverse().find((p) => typeof p.value === "number" && Number.isFinite(p.value));
        if (last) plots.push({ kind: "hline", title, value: last.value as number, color: o.color ?? "#8b949e" });
        continue;
      }
      plots.push({
        kind: "line", title: pts.find((p) => p.title)?.title ?? title, overlay: Boolean(o.overlay), hidden: o.display === "none",
        color: o.color ?? "#2962ff",
        data: pts
          .filter((p) => typeof p.value === "number" && Number.isFinite(p.value))
          .map((p) => [Math.round(p.time / 1000), p.value as number, p.options?.color ?? null]),
      });
    }
    const indicator = run.indicator ?? {};
    ctx.postMessage({
      id, ok: true, title: indicator.title ?? indicator.shorttitle ?? "Pine",
      overlay: Boolean(indicator.overlay ?? plots.some((p) => p.kind === "line" && p.overlay)),
      plots, warnings: (run.warnings ?? []).map(String).slice(0, 20),
    });
  } catch (err) {
    ctx.postMessage({ id, ok: false, error: String((err as Error)?.message ?? err).slice(0, 2000) });
  }
};
