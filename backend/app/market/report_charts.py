"""Server-side SVG charts for reports (pure Python, no dependencies). Rendered from the stored DB snapshot;
all text is escaped. The frontend embeds them as <img src="data:image/svg+xml;base64,...">
(no script context)."""

import base64
import math
from html import escape
from typing import Any

W, H = 720, 300
PAD_L, PAD_R, PAD_T, PAD_B = 64, 16, 40, 48
BG, GRID, AXIS, TEXT = "#ffffff", "#e5e7eb", "#9ca3af", "#111827"
COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed"]


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi == lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, v = [], start
    while v <= hi + step * 0.5:
        ticks.append(round(v, 10))
        v += step
    return ticks


def fmt_num(v: float) -> str:
    a = abs(v)
    for div, unit in ((1e12, " Bio."), (1e9, " Mrd."), (1e6, " Mio."), (1e3, " Tsd.")):
        if a >= div:
            return _de(v / div, 1) + unit
    return _de(v, 0 if a >= 100 else 1 if a >= 10 else 2)


def _de(v: float, d: int) -> str:
    """German number format (1.234,5)."""
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _frame(title: str, ticks: list[float], y: Any, suffix: str) -> list[str]:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'font-family="Helvetica, Arial, sans-serif" font-size="11">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        f'<text x="{PAD_L}" y="22" font-size="14" font-weight="bold" fill="{TEXT}">{escape(title)}</text>',
    ]
    for t in ticks:
        yy = y(t)
        parts.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="{GRID}"/>')
        parts.append(
            f'<text x="{PAD_L - 6}" y="{yy + 4:.1f}" text-anchor="end" fill="{AXIS}">'
            f"{escape(fmt_num(t) + suffix)}</text>"
        )
    return parts


def _legend(names: list[str]) -> list[str]:
    parts, x = [], PAD_L
    for i, n in enumerate(names):
        c = COLORS[i % len(COLORS)]
        parts.append(f'<rect x="{x}" y="{H - 16}" width="10" height="10" fill="{c}"/>')
        parts.append(f'<text x="{x + 14}" y="{H - 7}" fill="{TEXT}">{escape(n)}</text>')
        x += 24 + 7 * len(n)
    return parts


def bar_chart(
    title: str, labels: list[str], series: list[tuple[str, list[float | None]]], suffix: str = ""
) -> str | None:
    vals = [v for _, s in series for v in s if v is not None]
    if not labels or not vals:
        return None
    ticks = _nice_ticks(min(0.0, min(vals)), max(0.0, max(vals)))
    lo, hi = ticks[0], ticks[-1]
    ph = H - PAD_T - PAD_B

    def y(v: float) -> float:
        return PAD_T + ph * (1 - (v - lo) / (hi - lo))

    parts = _frame(title, ticks, y, suffix)
    group = (W - PAD_L - PAD_R) / len(labels)
    bw = group * 0.8 / len(series)
    for i, lab in enumerate(labels):
        gx = PAD_L + i * group + group * 0.1
        for j, (_, s) in enumerate(series):
            v = s[i] if i < len(s) else None
            if v is None:
                continue
            y0, y1 = y(0), y(v)
            parts.append(
                f'<rect x="{gx + j * bw:.1f}" y="{min(y0, y1):.1f}" width="{bw * 0.92:.1f}" '
                f'height="{abs(y1 - y0):.1f}" fill="{COLORS[j % len(COLORS)]}"/>'
            )
        parts.append(
            f'<text x="{PAD_L + (i + 0.5) * group:.1f}" y="{H - PAD_B + 14}" text-anchor="middle" '
            f'fill="{AXIS}">{escape(lab)}</text>'
        )
    parts += [*_legend([n for n, _ in series]), "</svg>"]
    return "".join(parts)


def line_chart(
    title: str, labels: list[str], series: list[tuple[str, list[float | None]]], suffix: str = ""
) -> str | None:
    vals = [v for _, s in series for v in s if v is not None]
    if len(labels) < 2 or not vals:
        return None
    ticks = _nice_ticks(min(vals), max(vals))
    lo, hi = ticks[0], ticks[-1]
    ph, pw = H - PAD_T - PAD_B, W - PAD_L - PAD_R

    def y(v: float) -> float:
        return PAD_T + ph * (1 - (v - lo) / (hi - lo))

    def x(i: int) -> float:
        return PAD_L + pw * i / (len(labels) - 1)

    parts = _frame(title, ticks, y, suffix)
    for j, (_, s) in enumerate(series):
        pts = [f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(s) if v is not None]
        if len(pts) > 1:
            parts.append(
                f'<polyline points="{" ".join(pts)}" fill="none" stroke="{COLORS[j % len(COLORS)]}" '
                f'stroke-width="2"/>'
            )
    step = max(1, len(labels) // 10)
    for i in range(0, len(labels), step):
        parts.append(
            f'<text x="{x(i):.1f}" y="{H - PAD_B + 14}" text-anchor="middle" fill="{AXIS}">'
            f"{escape(labels[i])}</text>"
        )
    parts += [*_legend([n for n, _ in series]), "</svg>"]
    return "".join(parts)


def _col(rows: list[dict[str, Any]], key: str) -> list[float | None]:
    return [r.get(key) for r in rows]


def build(snapshot: dict[str, Any]) -> dict[str, str]:
    """Chart id -> SVG markup."""
    a = snapshot.get("annual") or []
    cur = snapshot["instrument"]["currency"]
    labels = [str(r["fiscal_year"]) for r in a]
    charts: dict[str, str | None] = {
        "revenue_earnings": bar_chart(
            f"Umsatz, Nettogewinn und Free Cashflow ({cur})",
            labels,
            [
                ("Umsatz", _col(a, "revenue")),
                ("Nettogewinn", _col(a, "net_income")),
                ("Free Cashflow", _col(a, "free_cf")),
            ],
        ),
        "margins": line_chart(
            "Margen",
            labels,
            [
                ("Operative Marge", _col(a, "operating_margin_pct")),
                ("Nettomarge", _col(a, "net_margin_pct")),
                ("FCF-Marge", _col(a, "fcf_margin_pct")),
            ],
            " %",
        ),
        "per_share": line_chart(
            f"Gewinn und Dividende je Aktie ({cur})",
            labels,
            [("EPS (verwässert)", _col(a, "eps_diluted")), ("Dividende", _col(a, "dps"))],
        ),
        "balance": bar_chart(
            f"Bilanz ({cur})",
            labels,
            [
                ("Eigenkapital", _col(a, "equity")),
                ("Finanzschulden", _col(a, "debt")),
                ("Cash", _col(a, "cash")),
            ],
        ),
    }
    prices = snapshot.get("prices_yearly") or []
    # FV of the fiscal year that ended in that calendar year (FY ending Jan 2025 -> 2025)
    fv_hist = {
        int(h["date"][:4]): h["value"] for h in (snapshot.get("valuation") or {}).get("history_fv") or []
    }
    if prices:
        charts["price_fv"] = line_chart(
            f"Kurs (Jahresende) und fairer Wert ({cur})",
            [str(p["year"]) for p in prices],
            [
                ("Kurs", [p["close"] for p in prices]),
                ("Fairer Wert (bereinigt)", [fv_hist.get(p["year"]) for p in prices]),
            ],
        )
    return {k: v for k, v in charts.items() if v}


def data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
