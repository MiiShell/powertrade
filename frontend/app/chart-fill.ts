import type {
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from "lightweight-charts";

type Pt = [number, number];

/** Pine `fill()` between two plots: draws a polygon between the upper and lower line (series primitive). */
export class BandFill implements ISeriesPrimitive<Time> {
  private p: SeriesAttachedParameter<Time> | null = null;
  constructor(private readonly a: Pt[], private readonly b: Pt[], private readonly color: string) {}

  attached(param: SeriesAttachedParameter<Time>) {
    this.p = param;
  }

  detached() {
    this.p = null;
  }

  paneViews(): IPrimitivePaneView[] {
    const renderer: IPrimitivePaneRenderer = { draw: (target) => this.draw(target) };
    return [{ zOrder: () => "bottom", renderer: () => renderer }];
  }

  private draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]) {
    if (!this.p) return;
    const { chart, series } = this.p;
    const ts = chart.timeScale();
    const other = new Map(this.b);
    const pts: [number, number, number][] = [];
    for (const [t, v] of this.a) {
      const w = other.get(t);
      if (w === undefined) continue;
      const x = ts.timeToCoordinate(t as UTCTimestamp);
      const y1 = series.priceToCoordinate(v);
      const y2 = series.priceToCoordinate(w);
      if (x !== null && y1 !== null && y2 !== null) pts.push([x, y1, y2]);
    }
    if (pts.length < 2) return;
    target.useMediaCoordinateSpace(({ context: c }) => {
      c.beginPath();
      pts.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y)));
      for (let i = pts.length - 1; i >= 0; i--) c.lineTo(pts[i]![0], pts[i]![2]);
      c.closePath();
      c.fillStyle = this.color;
      c.fill();
    });
  }
}

/** Pine colours come as #RRGGBB or #RRGGBBAA -> rgba() understood everywhere. */
export function toRgba(color: string | null | undefined, fallback = "#2962ff"): string {
  const c = color ?? fallback;
  const m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(c);
  if (!m) return c;
  const n = parseInt(m[1]!, 16);
  const a = m[2] ? parseInt(m[2], 16) / 255 : 1;
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a.toFixed(3)})`;
}
