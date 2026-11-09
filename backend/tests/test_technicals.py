import math

import pytest

from app.market.technicals import (
    adx,
    cci,
    compute_rating,
    hma,
    ichimoku,
    label,
    stoch,
    summarize,
    ultimate,
    vwma,
    williams_r,
)


def _series(n: int = 300, trend: float = 0.5):  # type: ignore[no-untyped-def]
    c = [100 + trend * i + 5 * math.sin(i / 7) for i in range(n)]
    o = [c[i - 1] if i else c[0] for i in range(n)]
    h = [max(o[i], c[i]) + 1 for i in range(n)]
    lo = [min(o[i], c[i]) - 1 for i in range(n)]
    v = [1000.0 + (i % 10) for i in range(n)]
    return o, h, lo, c, v


def test_labels() -> None:
    assert [label(x) for x in (0.6, 0.3, 0.0, -0.3, -0.6, None)] == [
        "strong_buy",
        "buy",
        "neutral",
        "sell",
        "strong_sell",
        "neutral",
    ]


def test_bounded_oscillators() -> None:
    _o, h, lo, c, _v = _series()
    k, _d = stoch(h, lo, c)
    assert all(0 <= x <= 100 for x in k if x is not None)
    assert all(-100 <= x <= 0 for x in williams_r(h, lo, c) if x is not None)
    assert all(0 <= x <= 100 for x in ultimate(h, lo, c) if x is not None)
    a, _p, _m = adx(h, lo, c)
    assert all(0 <= x <= 100 for x in a if x is not None)
    assert cci(h, lo, c)[-1] is not None


def test_vwma_hma_ichimoku() -> None:
    c = [float(i) for i in range(1, 60)]
    assert vwma(c, [1.0] * len(c), 20)[-1] == pytest.approx(sum(c[-20:]) / 20)
    assert vwma(c, [None] * len(c), 20)[-1] is None
    assert hma(c, 9)[-1] == pytest.approx(c[-1], abs=1e-9)  # HMA has no lag on a straight line
    ich = ichimoku([x + 1 for x in c], [x - 1 for x in c])
    assert ich["base"] == pytest.approx((c[-1] + 1 + c[-26] - 1) / 2)


def test_uptrend_rates_buy_downtrend_sell() -> None:
    up = summarize(compute_rating(*_series(trend=1.0)))
    down = summarize(compute_rating(*_series(trend=-0.3)))
    assert up["moving_averages"]["label"] in ("buy", "strong_buy")  # type: ignore[index]
    assert down["moving_averages"]["label"] in ("sell", "strong_sell")  # type: ignore[index]
    assert len(up["oscillators"]["rows"]) == 11 and len(up["moving_averages"]["rows"]) == 15  # type: ignore[index]
    counts = up["summary"]["counts"]  # type: ignore[index]
    assert sum(counts.values()) == 26


def test_short_history_does_not_crash() -> None:
    o, h, lo, c, v = _series(n=30)
    s = summarize(compute_rating(o, h, lo, c, v))
    rows = s["moving_averages"]["rows"]  # type: ignore[index]
    assert next(r for r in rows if r["name"] == "Simple Moving Average (200)")["value"] is None


def test_ichimoku_neutral_when_cloud_disagrees() -> None:
    from app.market.technicals import Rating, compute_rating

    # downtrend after a rally: price below cloud, but lead line 1 still above lead line 2 -> neutral
    c = [100 + i for i in range(80)] + [180 - 3 * i for i in range(25)]
    o = [c[i - 1] if i else c[0] for i in range(len(c))]
    h = [max(a, b) + 1 for a, b in zip(o, c, strict=True)]
    lo = [min(a, b) - 1 for a, b in zip(o, c, strict=True)]
    r: Rating = compute_rating(o, h, lo, c, [1.0] * len(c))
    ich = next(x for x in r.moving_averages if x.name.startswith("Ichimoku"))
    assert ich.action in (0, -1)
