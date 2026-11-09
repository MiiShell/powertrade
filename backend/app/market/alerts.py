"""Price alerts: rule validation, evaluation (edge-triggered + cooldown), event history, delivery.

Rules are evaluated after each successful ingestion of their instrument (latest daily candle, which is
still open during the trading day). A rule fires when its condition changes from not-met to met and the
cooldown since the last trigger has passed. MA-cross rules never fire on their first evaluation (the
current side of the MA is only recorded), so a new rule does not report an old cross.
"""

import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.market import indicators
from app.market.notify import Notifier, NotifyError

log = logging.getLogger(__name__)

KIND_LABEL = {
    "price_above": "Kurs über",
    "price_below": "Kurs unter",
    "change_pct": "Kursänderung",
    "ma_cross_above": "Kurs kreuzt MA nach oben",
    "ma_cross_below": "Kurs kreuzt MA nach unten",
    "rsi_above": "RSI über",
    "rsi_below": "RSI unter",
    "fv_upside_above": "Abstand zum fairen Wert ≥",
}
KINDS = tuple(KIND_LABEL)
CROSS_KINDS = {"ma_cross_above", "ma_cross_below"}
STOCK_ONLY = {"fv_upside_above"}
HISTORY_BARS = 1200  # enough warm-up for EMA/SMA up to 400
MAX_RULES = 500


def _num(params: dict[str, Any], key: str, lo: float, hi: float, default: float | None = None) -> float:
    v = params.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise ValueError(f"{key}: number required")
    if not lo <= v <= hi:
        raise ValueError(f"{key} must be {lo:g}..{hi:g}")
    return float(v)


def _int(params: dict[str, Any], key: str, lo: int, hi: int, default: int | None = None) -> int:
    v = _num(params, key, lo, hi, default)
    if v != int(v):
        raise ValueError(f"{key}: integer required")
    return int(v)


def validate(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    """Normalised params for a rule kind (unknown keys are dropped). Raises ValueError."""
    if kind in ("price_above", "price_below"):
        return {"price": _num(params, "price", 1e-6, 1e9)}
    if kind == "change_pct":
        pct = _num(params, "pct", -99, 1000)
        if pct == 0:
            raise ValueError("pct must not be 0")
        return {"pct": pct, "days": _int(params, "days", 1, 365, 1)}
    if kind in CROSS_KINDS:
        ma = params.get("ma", "sma")
        if ma not in ("sma", "ema"):
            raise ValueError("ma must be sma or ema")
        return {"ma": ma, "period": _int(params, "period", 2, 400, 200)}
    if kind in ("rsi_above", "rsi_below"):
        return {"level": _num(params, "level", 1, 99), "period": _int(params, "period", 2, 100, 14)}
    if kind == "fv_upside_above":
        return {"pct": _num(params, "pct", -90, 500)}
    raise ValueError(f"unknown kind: {kind}")


@dataclass(frozen=True)
class Condition:
    state: bool | None  # None = not enough data (state unchanged)
    value: float | None


def condition(kind: str, params: dict[str, Any], closes: list[float], fv_upside: float | None) -> Condition:
    if not closes:
        return Condition(None, None)
    price = closes[-1]
    if kind == "price_above":
        return Condition(price >= params["price"], price)
    if kind == "price_below":
        return Condition(price <= params["price"], price)
    if kind == "change_pct":
        days = params["days"]
        if len(closes) <= days or closes[-1 - days] <= 0:
            return Condition(None, None)
        chg = (price / closes[-1 - days] - 1) * 100
        return Condition(chg >= params["pct"] if params["pct"] > 0 else chg <= params["pct"], chg)
    if kind in CROSS_KINDS:
        fn = indicators.sma if params["ma"] == "sma" else indicators.ema
        ma = fn(closes, params["period"])[-1]
        if ma is None:
            return Condition(None, None)
        return Condition(price > ma if kind == "ma_cross_above" else price < ma, ma)
    if kind in ("rsi_above", "rsi_below"):
        r = indicators.rsi(closes, params["period"])[-1]
        if r is None:
            return Condition(None, None)
        return Condition(r >= params["level"] if kind == "rsi_above" else r <= params["level"], r)
    if kind == "fv_upside_above":
        if fv_upside is None:
            return Condition(None, None)
        return Condition(fv_upside >= params["pct"], fv_upside)
    raise ValueError(f"unknown kind: {kind}")


def should_fire(
    kind: str,
    state: bool | None,
    last_state: bool | None,
    last_triggered_at: datetime | None,
    cooldown_minutes: int,
    now: datetime,
) -> bool:
    if state is not True or last_state is True:
        return False
    if kind in CROSS_KINDS and last_state is None:
        return False  # first evaluation only records the side of the MA
    return last_triggered_at is None or now - last_triggered_at >= timedelta(minutes=cooldown_minutes)


def _n(v: float | None, d: int = 2) -> str:
    if v is None:
        return "-"
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def describe(kind: str, params: dict[str, Any]) -> str:
    if kind in ("price_above", "price_below"):
        return f"{KIND_LABEL[kind]} {_n(params['price'])}"
    if kind == "change_pct":
        op = "≥" if params["pct"] > 0 else "≤"
        return f"Kursänderung {op} {_n(params['pct'], 1)} % in {params['days']} T."
    if kind in CROSS_KINDS:
        side = "nach oben" if kind == "ma_cross_above" else "nach unten"
        return f"Kurs kreuzt {params['ma'].upper()}{params['period']} {side}"
    if kind in ("rsi_above", "rsi_below"):
        return f"RSI{params['period']} {'über' if kind == 'rsi_above' else 'unter'} {_n(params['level'], 0)}"
    return f"Abstand zum fairen Wert ≥ {_n(params['pct'], 1)} %"


def message(
    symbol: str,
    currency: str,
    kind: str,
    params: dict[str, Any],
    value: float | None,
    price: float,
    note: str,
) -> str:
    """Plain text (no markup: Telegram is sent without parse_mode)."""
    unit = {"change_pct": " %", "fv_upside_above": " %"}.get(kind, "")
    detail = "" if kind in ("price_above", "price_below") else f" · Wert {_n(value)}{unit}"
    lines = [f"🔔 {symbol}: {describe(kind, params)}", f"Kurs {_n(price)} {currency}{detail}"]
    if note:
        lines.append(f"Notiz: {note}")
    return "\n".join(lines)


# ---------------------------------------------------------------- DB layer

# Static statement; optional filters are NULL-able parameters (no dynamic SQL).
RULES_SQL = text("""
    SELECT a.id, a.instrument_id, i.symbol, i.name, i.type, i.currency, a.kind, a.params, a.note,
           a.cooldown_minutes, a.notify_telegram, a.is_active, a.last_state, a.last_value,
           a.last_evaluated_at, a.last_triggered_at, a.created_at
    FROM alert a JOIN instrument i ON i.id = a.instrument_id
    WHERE (CAST(:iid AS bigint) IS NULL OR a.instrument_id = :iid)
      AND (CAST(:id AS bigint) IS NULL OR a.id = :id)
      AND (NOT CAST(:active_only AS boolean) OR a.is_active)
    ORDER BY i.symbol, a.id
""")


def _rules_params(
    iid: int | None = None, rid: int | None = None, active_only: bool = False
) -> dict[str, Any]:
    return {"iid": iid, "id": rid, "active_only": active_only}


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


def _rule_out(r: Any) -> dict[str, Any]:
    d = {k: _iso(v) for k, v in dict(r).items()}
    d["params"] = dict(r["params"])
    d["description"] = describe(r["kind"], d["params"])
    return d


async def list_rules(engine: AsyncEngine, instrument_id: int | None = None) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(RULES_SQL, _rules_params(iid=instrument_id))
        return [_rule_out(r) for r in rows.mappings()]


async def get_rule(engine: AsyncEngine, rule_id: int) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        r = (await conn.execute(RULES_SQL, _rules_params(rid=rule_id))).mappings().first()
    return _rule_out(r) if r else None


async def create_rule(engine: AsyncEngine, body: dict[str, Any]) -> int:
    async with engine.begin() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM alert"))
        if (count or 0) >= MAX_RULES:
            raise ValueError(f"max. {MAX_RULES} alerts")
        rid = await conn.scalar(
            text("""
            INSERT INTO alert (instrument_id, kind, params, note, cooldown_minutes, notify_telegram,
                               is_active)
            VALUES (:iid, :k, CAST(:p AS jsonb), :n, :c, :t, :a) RETURNING id"""),
            {
                "iid": body["instrument_id"],
                "k": body["kind"],
                "p": json.dumps(body["params"]),
                "n": body["note"],
                "c": body["cooldown_minutes"],
                "t": body["notify_telegram"],
                "a": body["is_active"],
            },
        )
    return int(rid)


async def update_rule(engine: AsyncEngine, rule_id: int, body: dict[str, Any]) -> bool:
    """Changing kind/params resets the edge state (re-arms the rule)."""
    async with engine.begin() as conn:
        res = await conn.execute(
            text("""
            UPDATE alert SET
              last_state = CASE WHEN kind = :k AND params = CAST(:p AS jsonb) THEN last_state END,
              kind = :k, params = CAST(:p AS jsonb), note = :n, cooldown_minutes = :c, notify_telegram = :t,
              is_active = :a, updated_at = now()
            WHERE id = :id"""),
            {
                "id": rule_id,
                "k": body["kind"],
                "p": json.dumps(body["params"]),
                "n": body["note"],
                "c": body["cooldown_minutes"],
                "t": body["notify_telegram"],
                "a": body["is_active"],
            },
        )
    return bool(res.rowcount)


async def delete_rule(engine: AsyncEngine, rule_id: int) -> bool:
    async with engine.begin() as conn:
        res = await conn.execute(text("DELETE FROM alert WHERE id = :id"), {"id": rule_id})
    return bool(res.rowcount)


async def events(engine: AsyncEngine, limit: int = 100, instrument_id: int | None = None) -> dict[str, Any]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
            SELECT e.id, e.alert_id, e.instrument_id, i.symbol, e.kind, e.triggered_at, e.value, e.message,
                   e.delivery, e.delivery_error, e.read_at
            FROM alert_event e JOIN instrument i ON i.id = e.instrument_id
            WHERE CAST(:iid AS bigint) IS NULL OR e.instrument_id = :iid
            ORDER BY e.triggered_at DESC, e.id DESC LIMIT :lim"""),
            {"lim": limit, "iid": instrument_id},
        )
        out = [{k: _iso(v) for k, v in dict(r).items()} for r in rows.mappings()]
        unread = await conn.scalar(text("SELECT count(*) FROM alert_event WHERE read_at IS NULL"))
    return {"events": out, "unread": int(unread or 0)}


async def mark_read(engine: AsyncEngine) -> int:
    async with engine.begin() as conn:
        res = await conn.execute(text("UPDATE alert_event SET read_at = now() WHERE read_at IS NULL"))
    return int(res.rowcount or 0)


async def instruments_with_rules(engine: AsyncEngine) -> set[int]:
    async with engine.connect() as conn:
        return {
            r[0] for r in await conn.execute(text("SELECT DISTINCT instrument_id FROM alert WHERE is_active"))
        }


async def evaluate_instrument(
    engine: AsyncEngine, notifier: Notifier, iid: int, now: datetime | None = None
) -> int:
    """Evaluate all active rules of one instrument; returns the number of triggered alerts."""
    now = now or datetime.now(UTC)
    async with engine.connect() as conn:
        rules = (await conn.execute(RULES_SQL, _rules_params(iid=iid, active_only=True))).mappings().all()
        if not rules:
            return 0
        closes = [
            float(r[0])
            for r in await conn.execute(
                text(
                    "SELECT close FROM (SELECT ts, close FROM price_bar_1d WHERE instrument_id = :iid "
                    "ORDER BY ts DESC LIMIT :n) s ORDER BY ts"
                ),
                {"iid": iid, "n": HISTORY_BARS},
            )
        ]
    if not closes:
        return 0
    fv_upside: float | None = None
    if any(r["kind"] in STOCK_ONLY for r in rules) and rules[0]["type"] == "stock":
        from app.market.stockdata import fair_value_summary  # local import: avoids import cycle

        summary = await fair_value_summary(engine, iid)
        fv_upside = summary.get("upside") if summary.get("available") else None

    fired = 0
    for r in rules:
        params = dict(r["params"])
        cond = condition(r["kind"], params, closes, fv_upside)
        fire = should_fire(
            r["kind"], cond.state, r["last_state"], r["last_triggered_at"], r["cooldown_minutes"], now
        )
        event_id = None
        msg = message(r["symbol"], r["currency"], r["kind"], params, cond.value, closes[-1], r["note"])
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                UPDATE alert SET last_state = COALESCE(CAST(:s AS boolean), last_state),
                       last_value = CAST(:v AS double precision), last_evaluated_at = :now,
                       last_triggered_at = CASE WHEN CAST(:fire AS boolean) THEN :now
                                                ELSE last_triggered_at END
                WHERE id = :id"""),
                {"s": cond.state, "v": cond.value, "now": now, "fire": fire, "id": r["id"]},
            )
            if fire:
                event_id = await conn.scalar(
                    text("""
                    INSERT INTO alert_event
                        (alert_id, instrument_id, kind, triggered_at, value, message, delivery)
                    VALUES (:aid, :iid, :k, :now, CAST(:v AS double precision), :m, 'pending')
                    RETURNING id"""),
                    {"aid": r["id"], "iid": iid, "k": r["kind"], "now": now, "v": cond.value, "m": msg},
                )
        if event_id is None:
            continue
        fired += 1
        delivery, error = "skipped", None
        if r["notify_telegram"] and notifier.configured:
            try:
                await notifier.send(msg)
                delivery = "sent"
            except NotifyError as exc:
                delivery, error = "failed", str(exc)[:300]
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE alert_event SET delivery = :d, delivery_error = :e WHERE id = :id"),
                {"d": delivery, "e": error, "id": event_id},
            )
        log.info("alert fired rule=%s instrument=%s delivery=%s", r["id"], iid, delivery)
    return fired
