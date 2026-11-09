"""Claude stock reports: budget guard, versioned storage, worker run, Markdown export."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.market import chart_analysis as budget
from app.market import report_charts
from app.market.report_agent import REPORT_COST_CAP_USD, ReportAgent, check_numbers
from app.market.report_data import collect


async def create(engine: AsyncEngine, iid: int, model: str, monthly_budget: float, daily_limit: int) -> int:
    snap = await collect(engine, iid)  # raises LookupError / ValueError
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(7007)"))  # same lock as chart analyses
        u = await budget.usage(engine, monthly_budget, 0)
        today = await conn.scalar(
            text("SELECT count(*) FROM report WHERE created_at >= date_trunc('day', now())")
        )
        if (today or 0) >= daily_limit:
            raise budget.BudgetError(f"Tageslimit erreicht ({daily_limit} Berichte)")
        if u["remaining_usd"] < REPORT_COST_CAP_USD:
            raise budget.BudgetError(
                f"Monatsbudget reicht nicht (frei {u['remaining_usd']:.2f} $, Bericht reserviert "
                f"{REPORT_COST_CAP_USD:.2f} $)"
            )
        version = await conn.scalar(
            text("SELECT COALESCE(max(version), 0) + 1 FROM report WHERE instrument_id = :iid"), {"iid": iid}
        )
        rid = await conn.scalar(
            text("""
            INSERT INTO report (instrument_id, version, model, status, reserved_usd, snapshot)
            VALUES (:iid, :v, :m, 'queued', :r, CAST(:s AS jsonb)) RETURNING id"""),
            {"iid": iid, "v": version, "m": model, "r": REPORT_COST_CAP_USD, "s": json.dumps(snap)},
        )
    return int(rid)


async def _finish(engine: AsyncEngine, rid: int, values: dict[str, Any]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("""
            UPDATE report SET status = :status, sections = CAST(:sections AS jsonb),
                   charts = CAST(:charts AS jsonb),
                   sources = CAST(:sources AS jsonb), warnings = CAST(:warnings AS jsonb),
                   stats = CAST(:stats AS jsonb), error = :error, reserved_usd = 0, finished_at = now()
            WHERE id = :id"""),
            {
                "id": rid,
                **{k: values.get(k) for k in ("status", "error")},
                **{
                    k: json.dumps(values[k]) if values.get(k) is not None else None
                    for k in ("sections", "charts", "sources", "warnings", "stats")
                },
            },
        )


async def run(engine: AsyncEngine, agent: ReportAgent, rid: int) -> str:
    async with engine.begin() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "UPDATE report SET status = 'running' WHERE id = :id AND status = 'queued' "
                        "RETURNING model, snapshot"
                    ),
                    {"id": rid},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return "skipped"
    if not agent.configured:
        await _finish(
            engine,
            rid,
            {
                "status": "failed",
                "error": "Anthropic API-Key nicht konfiguriert (./scripts/set-secret.sh anthropic_api_key)",
            },
        )
        return "failed"
    snap = dict(row["snapshot"])
    res = await agent.run(snap, row["model"])
    if res.turns or res.input_tokens:
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                INSERT INTO ai_call_log (feature, ref_id, model_requested, model_served, status,
                    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, error)
                VALUES ('report', :ref, :mr, :ms, :st, :it, :ot, :cr, :cw, :c, :err)"""),
                {
                    "ref": rid,
                    "mr": row["model"],
                    "ms": res.model_served,
                    "st": res.status,
                    "it": res.input_tokens,
                    "ot": res.output_tokens,
                    "cr": res.cache_read_tokens,
                    "cw": res.cache_write_tokens,
                    "c": res.cost_usd,
                    "err": res.error,
                },
            )
    stats = {
        "turns": res.turns,
        "web_searches": res.web_searches,
        "input_tokens": res.input_tokens,
        "output_tokens": res.output_tokens,
        "cache_read_tokens": res.cache_read_tokens,
        "cost_usd": res.cost_usd,
        "model_served": res.model_served,
    }
    if res.status != "ok" or not res.sections:
        await _finish(
            engine,
            rid,
            {
                "status": "refused" if res.status == "refused" else "failed",
                "error": res.error,
                "stats": stats,
            },
        )
        return "refused" if res.status == "refused" else "failed"
    sources = [{**s, "verified": s["url"] in res.searched_urls} for s in res.sections.get("sources", [])]
    await _finish(
        engine,
        rid,
        {
            "status": "done",
            "sections": res.sections,
            "charts": report_charts.build(snap),
            "sources": sources,
            "warnings": check_numbers(res.sections, snap),
            "stats": stats,
        },
    )
    return "done"


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


async def get(engine: AsyncEngine, rid: int) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        r = (
            (
                await conn.execute(
                    text("""
            SELECT r.*, i.symbol, i.name FROM report r JOIN instrument i ON i.id = r.instrument_id
            WHERE r.id = :id"""),
                    {"id": rid},
                )
            )
            .mappings()
            .first()
        )
    if r is None:
        return None
    d = {k: _iso(v) for k, v in dict(r).items()}
    d["reserved_usd"] = float(d["reserved_usd"] or 0)
    d["charts"] = {k: report_charts.data_uri(v) for k, v in (r["charts"] or {}).items()}
    return d


async def history(engine: AsyncEngine, iid: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
            SELECT r.id, r.instrument_id, i.symbol, i.name, r.version, r.model, r.status, r.error,
                   r.created_at, r.finished_at, r.sections->>'title' AS title,
                   (r.stats->>'cost_usd')::float AS cost_usd,
                   jsonb_array_length(COALESCE(r.warnings, '[]'::jsonb)) AS warnings
            FROM report r JOIN instrument i ON i.id = r.instrument_id
            WHERE CAST(:iid AS bigint) IS NULL OR r.instrument_id = :iid
            ORDER BY r.created_at DESC LIMIT :n"""),
            {"iid": iid, "n": limit},
        )
        return [{k: _iso(v) for k, v in dict(r).items()} for r in rows.mappings()]


def _n(v: Any, d: int = 2) -> str:
    if v is None:
        return "–"
    if isinstance(v, int | float):
        return (
            report_charts.fmt_num(float(v))
            if abs(v) >= 1e3
            else f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
    return str(v)


ANNUAL_COLS = [
    ("revenue", "Umsatz"),
    ("net_income", "Nettogewinn"),
    ("eps_diluted", "EPS"),
    ("operating_margin_pct", "Op. Marge %"),
    ("net_margin_pct", "Nettomarge %"),
    ("free_cf", "Free Cashflow"),
    ("dps", "Dividende"),
    ("net_debt", "Nettoschulden"),
    ("pb", "KBV"),
]


def to_markdown(rep: dict[str, Any]) -> str:
    s, snap = rep["sections"] or {}, rep["snapshot"]
    inst, mk, val = snap["instrument"], snap["market"], snap["valuation"]
    cur = inst["currency"]
    out = [
        f"# {s.get('title') or inst['name']}",
        "",
        f"*{inst['name']} ({inst['symbol']}) · Version {rep['version']} · Datenstand {snap['as_of']} · "
        f"KI-generiert ({rep['model']}), keine Anlageberatung*",
        "",
        "## Überblick",
        "",
        "| Kennzahl | Wert |",
        "|---|---|",
        f"| Kurs | {_n(mk.get('price'))} {cur} ({mk.get('date') or '-'}) |",
        f"| Marktkapitalisierung | {_n((snap.get('profile') or {}).get('market_cap'))} {cur} |",
        f"| Fairer Wert (bereinigt) | {_n(val.get('fv_std'))} {cur} ({_n(val.get('upside_pct'))} %) |",
        f"| Ø KGV ({val.get('period_years')} J.) | {_n((val.get('median_multiples') or {}).get('pe'))} |",
        f"| KBV aktuell / Median | {_n(val.get('pb_current'))} / {_n(val.get('pb_median_10y'))} |",
        f"| Dividendenrendite | {_n(val.get('dividend_yield_pct'))} % |",
        "",
        s.get("overview", ""),
        "",
    ]

    def sec(title: str, key: str) -> None:
        v = s.get(key)
        if not v:
            return
        out.extend([f"## {title}", ""])
        out.extend([f"- {x}" for x in v] if isinstance(v, list) else [v])
        out.append("")

    sec("Geschäftsmodell", "business_model")
    if s.get("segments"):
        out.extend(
            ["## Segmente", ""] + [f"- **{g['name']}**: {g['description']}" for g in s["segments"]] + [""]
        )
    sec("Investment-These", "investment_thesis")
    sec("Kursentwicklung", "price_history")
    sec("Operative Entwicklung & KPIs", "operating_performance")
    out.extend(
        ["| GJ | " + " | ".join(c[1] for c in ANNUAL_COLS) + " |", "|---|" + "---|" * len(ANNUAL_COLS)]
    )
    out.extend(
        f"| {a['fiscal_year']} | " + " | ".join(_n(a.get(k)) for k, _ in ANNUAL_COLS) + " |"
        for a in snap["annual"]
    )
    out.append("")
    sec("Ausblick / Guidance", "guidance")
    sec("Umsatz, Gewinn & Margen", "financials_comment")
    sec("Bilanz", "balance_sheet")
    sec("Kapitalallokation", "capital_allocation")
    sec("Bewertung", "valuation")
    sec("Chancen", "opportunities")
    sec("Risiken", "risks")
    sec("Fazit", "conclusion")
    out.extend(["## Quellen", "", "- Kennzahlen: PowerTrade-Datenbank (SEC EDGAR / FMP, Kurse Yahoo/Stooq)"])
    out.extend(
        f"- [{x['title']}]({x['url']}) – {x['used_for']}{'' if x.get('verified') else ' (nicht verifiziert)'}"
        for x in rep.get("sources") or []
    )
    if rep.get("warnings"):
        out.extend(["", "## Hinweise zur Zahlenprüfung", ""])
        out.extend(
            f"- „{w['number']}“ ({w['field']}) nicht in den Datenbankwerten gefunden" for w in rep["warnings"]
        )
    return "\n".join(out) + "\n"


async def expire_stale(engine: AsyncEngine, minutes: int = 30) -> int:
    async with engine.begin() as conn:
        res = await conn.execute(
            text("""
            UPDATE report SET status = 'failed', error = 'Zeitüberschreitung', reserved_usd = 0,
                   finished_at = now()
            WHERE status IN ('queued','running') AND created_at < now() - make_interval(mins => :m)"""),
            {"m": minutes},
        )
    return int(res.rowcount or 0)
