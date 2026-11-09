"""Bar model + sanitation shared by all providers."""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time


@dataclass(frozen=True, slots=True)
class Bar:
    ts: datetime  # 00:00 UTC of the trading day
    open: float
    high: float
    low: float
    close: float
    adj_close: float | None = None
    volume: float | None = None


def day_ts(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


def _finite_pos(x: object) -> bool:
    return isinstance(x, int | float) and math.isfinite(x) and x > 0


def sanitize(bars: list[Bar], today: date | None = None) -> list[Bar]:
    """Drop invalid/future bars, repair high/low envelope, dedupe by day (last wins), sort ascending."""
    limit = day_ts(today or datetime.now(UTC).date())
    out: dict[datetime, Bar] = {}
    for b in bars:
        if b.ts > limit or not all(_finite_pos(v) for v in (b.open, b.high, b.low, b.close)):
            continue
        high = max(b.high, b.open, b.close, b.low)
        low = min(b.low, b.open, b.close, b.high)
        adj = b.adj_close if b.adj_close is not None and _finite_pos(b.adj_close) else None
        vol = b.volume if b.volume is not None and math.isfinite(b.volume) and b.volume >= 0 else None
        out[b.ts] = Bar(b.ts, b.open, high, low, b.close, adj, vol)
    return [out[k] for k in sorted(out)]
