# PowerTrade — Build Prompt for Claude Code

## Role
You are a senior full-stack engineer with a strong security focus. You build a self-hosted, single-user
investment research & charting platform called **PowerTrade**. Work in small, verifiable increments.
Before writing code for a phase, output a short plan, then implement, test, and update `CHANGELOG.md`.
Ask me before any irreversible decision (schema breaking changes, paid APIs, deleting data).

## Goal
One web app that combines:
1. **TradingView-style charting** (SMA, EMA, RSI, seasonality)
2. **Aktienfinder-style fundamentals** (watchlist with scorecard, fair-value valuation, price alerts)
3. **Claude AI** (on-demand chart analysis + Abilitato-style stock reports)

## Fixed Decisions
| Area | Decision |
|---|---|
| Platform | Web app, self-hosted via Docker Compose (Mac for dev, Linux server for prod) |
| Users | Single user, but auth is mandatory |
| Frontend | Next.js (App Router) + TypeScript + Tailwind; charts via **TradingView Lightweight Charts** (Apache-2.0, keep attribution) |
| Backend | Python 3.12 + FastAPI + Pydantic v2; indicators via pandas/numpy (own implementations, unit-tested against known values) |
| Jobs | Worker + scheduler (ARQ or Celery + Redis) for ingestion, alerts, report generation |
| Database | PostgreSQL + **TimescaleDB** (hypertables for prices, continuous aggregates for 1h/1D/1W) |
| Data budget | Phase 1 free sources; Phase 2 optional paid provider (FMP Starter or EODHD) — must be a config switch, no code rewrite |
| AI | Anthropic API (Claude), server-side only |

## Features

### F1 — Charting
- Candlestick/OHLC, timeframes 5m/15m/1h/4h/1D/1W, ranges 1M…Max
- Indicators (configurable, persisted per user): SMA(n), EMA(n) (multiple, e.g. 21/50/200), RSI(14) with 30/70 bands + bullish/bearish divergence markers
- Horizontal support/resistance lines (draw, persist)
- **Seasonality panel**: normalized YTD performance of the current year vs. previous N years (like TradingView "Saisonal"), plus avg. monthly return heatmap
- Watchlist sidebar with last price, change, change %

### F2 — Stock list with scorecard (Aktienfinder-style)
- Columns: price, market cap, P/E, P/B, dividend yield, payout ratio, revenue/EPS CAGR (5/10y), earnings stability, debt ratio, fair value, upside %
- **Scorecard** (0–15 points, transparent formula shown in UI): earnings growth, earnings stability (R² of EPS trend), dividend growth/continuity, balance sheet quality, valuation vs. history
- Sort, filter, saved screens

### F3 — Fair-value valuation
- Methods (each shown separately + weighted blend): historical average P/E × forward EPS, historical P/B × book value, DCF (editable assumptions), Graham number, dividend discount model (dividend payers)
- Show 5/10/20y average P/E & P/B tables (as in Abilitato reports)
- Every number must link to its source + timestamp

### F4 — Price alerts
- Assets: stocks, ETFs, BTC (and other crypto)
- Types: price above/below, % change in X period, crosses SMA/EMA, RSI above/below, fair-value upside threshold
- Delivery: Telegram bot (primary), email, web push; dedup + cooldown; alert history

### F5 — Claude chart analysis (on demand)
- Button "Analyze with Claude" on the chart
- Send: rendered chart PNG **and** structured JSON (OHLCV window, indicator values, S/R levels, seasonality stats)
- Output (structured JSON → rendered): trend, key levels, momentum/RSI, divergences, scenarios (bull/base/bear) with invalidation levels, confidence
- Always display "no investment advice" disclaimer

### F6 — Claude reports (Abilitato-style, on demand)
Sections: Overview table · Business model · Segments · Investment thesis · Price history · Operating performance & KPIs ·
Guidance/Forecast · Revenue/Earnings/Margin charts · Balance sheet · Capital allocation (dividends, buybacks) ·
Valuation (P/E, P/B vs. history, fair value) · Opportunities & risks · Conclusion · Sources
- **Numbers come only from the DB** via tool use (function calling) — Claude writes text, never invents figures
- Charts generated server-side from DB data and embedded
- Store reports versioned; export as PDF/Markdown
- Cache + cost guard (max tokens/report, monthly budget limit in settings, show cost per report)

## Data Model (cross-references & dependencies)
Design normalized core tables, e.g.:
- `instrument` (id, type: stock/etf/crypto/index, isin, symbol, exchange, currency)
- `company`, `sector`, `industry`, `country`
- `etf_holding` (etf_id → instrument_id, weight, as_of) → exposure & overlap
- `price_bar` (hypertable: instrument_id, ts, timeframe, o/h/l/c/v)
- `fundamental_fact` (instrument_id, period, metric, value, source, fetched_at) — long format, point-in-time
- `valuation_snapshot`, `scorecard_snapshot`
- `relation` (from_id, to_id, type: supplier/competitor/peer/correlation, weight, as_of) — for dependency analysis
- `correlation` materialized view (rolling 90d/1y returns correlation)
- `alert`, `alert_event`, `report`, `ai_call_log`, `watchlist`, `chart_layout`
Use Alembic migrations. Add indexes for all FK and time queries.

## Data Sources (adapter pattern)
Interface `MarketDataProvider` / `FundamentalsProvider` / `CryptoProvider`; one adapter per source; source + fetch time stored per record.
- Phase 1 (free): Stooq / yfinance (unofficial — wrap with retries, treat as best effort), CoinGecko or Binance public API (crypto),
  SEC EDGAR companyfacts (US fundamentals), FMP free tier, ECB FX rates
- Phase 2 (paid, config switch): FMP or EODHD (EU stocks, ETF holdings, stable fundamentals)
- Respect rate limits & ToS; local caching; nightly fundamentals sync, intraday price polling only for watchlist

## Security Requirements (non-negotiable)
- Auth: passkey/WebAuthn or OIDC (e.g. Authelia/Authentik) behind reverse proxy (Caddy/Traefik) with TLS
- Secrets only via env/Docker secrets; never in repo, logs or frontend; `.env.example` only
- Anthropic + data API keys server-side only; backend proxies all external calls
- Treat all fetched content (news, filings, web) as untrusted → prompt-injection guard: pass as data in delimited blocks, no tool execution derived from it
- Input validation (Pydantic), parameterized SQL only, CSP + security headers, CSRF protection, rate limiting
- Least-privilege DB user; backups (pg_dump, encrypted) + restore test
- Dependency scanning (pip-audit, npm audit, Trivy for images), pre-commit with gitleaks
- Containers as non-root, read-only FS where possible, pinned image digests

## Engineering Standards
- Monorepo: `/frontend`, `/backend`, `/worker`, `/infra`, `/docs`
- Tests: pytest (indicators, valuation, scorecard with fixed fixtures), Playwright smoke tests for UI
- Lint/format: ruff + mypy (strict), eslint + prettier + tsc strict
- CI: GitHub Actions (lint, test, audit, build)
- Structured logging (JSON), health endpoints, simple metrics
- Docs: README (setup), ARCHITECTURE.md (diagram), ADRs for key decisions
- All code, comments and docs in English

## Phases (deliver one at a time, each runnable)
0. Repo scaffold, Docker Compose (db, redis, backend, worker, frontend, proxy), auth, CI
1. Data layer: schema, migrations, provider adapters, ingestion jobs (prices + crypto)
2. Charting: candles, SMA/EMA/RSI, S/R lines, watchlist
3. Seasonality panel
4. Fundamentals ingestion + stock list + scorecard
5. Fair-value engine + valuation tables
6. Alerts engine + Telegram/email/push
7. Claude chart analysis
8. Claude reports + PDF export + cost guard
9. Cross-reference views: ETF overlap, sector exposure, correlation matrix, relation graph
10. Hardening: security review, backups, performance, Phase-2 paid provider switch

## Definition of Done (per phase)
Tests green · lint/type-check clean · no secrets in diff · docs updated · `CHANGELOG.md` entry · short demo steps for me.

## Start
Begin with Phase 0. First show the plan and the final folder structure, then wait for my OK.
