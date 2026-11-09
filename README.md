# PowerTrade

Self-hosted charting & stock research with Claude integration. Spec: `PROMPT.md`, formulas: `docs/SCORING.md`.

## Architecture (Phase 0)

```
Browser ──HTTPS──> Caddy ─┬─ /api/* ─> backend (FastAPI) ─┬─> TimescaleDB (net: data, internal)
 (127.0.0.1:8443)         └─ /*     ─> frontend (Next.js) └─> Redis <── worker (ARQ)
```

- `data` network is `internal`: DB/Redis have no egress and are unreachable from Caddy/frontend.
- Secrets: Docker secrets from `./secrets` (gitignored), never env vars or images.
- DB roles: `powertrade` (owner, migrations only) and `powertrade_app` (DML only, used by API/worker).
- Auth: single admin, Argon2id password + optional TOTP, server-side sessions in Redis
  (cookie `HttpOnly; Secure; SameSite=Strict`), login throttling, Origin/Sec-Fetch-Site CSRF check.
- Containers: read-only FS, `cap_drop: ALL`, `no-new-privileges`, non-root app users.

## Requirements
Docker (Desktop/OrbStack/Colima) with Compose v2, `openssl`, `curl`.

## First setup
```bash
./scripts/init-secrets.sh      # creates .env + ./secrets, asks for admin password, optional TOTP
```

## Test deployment
```bash
./scripts/test-deploy.sh       # isolated stack, random secrets, smoke tests, migration roundtrip, teardown
KEEP=1 ./scripts/test-deploy.sh   # keep stack for debugging (project: powertrade-test)
```
Smoke tests (`tests/smoke/test_smoke.py`) verify: TLS chain, liveness/readiness (DB+Timescale, Redis, worker),
frontend, security headers, disabled API docs, auth required, wrong password/TOTP, CSRF block, cookie flags,
end-to-end selfcheck (API → queue → worker → DB write → API read), session revocation on logout,
forged cookie, DB/Redis not reachable from edge network, login rate limit.

## Production deployment (local)
```bash
./scripts/deploy.sh            # test deploy → build → backup → migrate → rollout → verify
```
Open https://localhost:8443. Trust the local CA once (command is printed by the script).

## Market data (Phase 1)
- Daily bars in `price_bar_1d` (TimescaleDB hypertable, compressed after 180 days); weekly bars via view `price_bar_1w` (Monday buckets).
- Providers (adapter pattern, fixed hosts, validated symbols, size/time limits): Yahoo chart API (primary),
  Stooq CSV (fallback stocks), Kraken OHLC (fallback crypto, max ~2 years). Order per instrument via `instrument_source.priority`.
- Worker: hourly `schedule_ingestion` (minute 5) → one `ingest` job per watched instrument; incremental with 7-day overlap, idempotent upsert, every run logged in `ingestion_run`.
- Test deploy uses `PT_PROVIDERS_MODE=fixture` (deterministic synthetic data, no network). Check live sources:
  `./scripts/check-sources.sh` (prod stack running).
- API: `GET /api/watchlist`, `POST /api/watchlist/items`, `DELETE /api/watchlist/items/{id}`,
  `POST /api/instruments/{id}/refresh`, `GET /api/instruments/{id}/bars?tf=1d|1w&start&end&limit`, `GET /api/ingestion/runs`.
- **Financial Modeling Prep (FMP)**: provider `fmp` (stable API, key sent as `apikey` header, never in URLs/logs).
  Free plan budget enforced in Redis: max **240 calls/day** (margin to 250), paced over the day
  (`20 + 240 × elapsed-day-fraction`), max **450 MB / 30 days** (limit 512 MB), HTTP 429 → blocked until next UTC day.
  History capped to 5 years. Default order for stocks/ETFs: Yahoo → FMP → Stooq (FMP quota reserved for fundamentals in Phase 4).
  Set key: `./scripts/set-secret.sh fmp_api_key` then `./scripts/deploy.sh`. Usage: `GET /api/providers/usage` / status panel.
- Yahoo/Stooq are unofficial free endpoints (best effort, ToS-grey). Paid provider = Phase 2 data switch.

## Charting (Phase 2)
- Chart tab (`#chart/<instrumentId>`): TradingView Lightweight Charts™ v5 (Apache-2.0, attribution logo kept), candles + volume,
  SMA/EMA overlays (up to 6 periods each, saved in the browser), RSI pane with 30/50/70 and regular bull/bear divergences,
  1D/1W, ranges 3M–Alle, OHLC legend, horizontal S/R lines (click to place, stored in `chart_level`, max 50 per instrument).
- Indicators are computed server-side (`app/market/indicators.py`, unit-tested against reference values) with extra warm-up
  history: `GET /api/instruments/{id}/chart?tf=1d&limit=3000&sma=20,50,200&ema=21&rsi=14`.
- Divergences: RSI pivots (5 left/5 right), pivot distance 5–60 bars; bull = price lower low + RSI higher low, bear = price higher high + RSI lower high.

## Asset details (Chart tab → Details, `#chart/<id>/details`)
- Header card: price, change, volume vs. Ø 30 days, day range, 52-week range, performance 1W–5Y, all-time high.
- Company profile (stocks/ETFs) imported from FMP `/stable/profile`, **cleaned** (`app/market/profile.py`: whitespace,
  length limits, ISIN/country/currency/website validation, finite numbers) and stored in `instrument_profile`;
  fills gaps in `instrument` (name, exchange, country, ISIN). Refreshed weekly, max 5 calls/hour, manual refresh 1×/day.
- Technical analysis 1 day/1 week/1 month: 11 oscillators + 15 moving averages with Buy/Neutral/Sell votes, three gauges
  (TradingView rating rules, simplified). Each successful ingest stores a rating snapshot in `technical_snapshot`.
- Pivots (Classic, Fibonacci, Camarilla, Woodie, DM) from the previous completed month (1D) or year (1W/1M);
  formulas verified against the TradingView BTC example.
- Seasonality: YTD % path per year vs. previous year's close, average of complete years, monthly-return heatmap, year range.

## Chart widgets & Pine Scripts
- Above the chart: price/volume, day range, week range, 52-week range (`GET /api/instruments/{id}/stats`).
- „Indikatoren ▾“: built-in RSI + divergences is now optional; any stored Pine Script can be toggled (saved per browser).
- Pine Scripts (v5/v6) run via **PineTS** in a dedicated Web Worker `/pine-worker.js` (bundled with esbuild at build time).
  Security: only the worker gets `'unsafe-eval'` and `connect-src 'none'` (no network, no DOM); the app CSP stays without eval.
  Runs are serialised with a 10 s kill-timeout. Scripts are stored in `pine_script` (max 100 KB, must declare `//@version=5|6`);
  scripts are never executed on the server.
- Built-in: `[Hoss] OBV RSI` (ported v4 → v5) and `[Hoss] VWAP Deviation` (read-only; duplicate to edit). PineTS quirks
  worked around: no `ta.*` calls nested inside ternaries passed to other `ta.*` calls; no `if`-expression assignment; no
  variable named `type`. Supported output: `plot` (incl. per-bar colours, `display.none`), `hline`, `fill`; not yet rendered:
  tables, labels, lines, boxes.
- Editor: „✎ Pine“ → new / edit / test (runs on current chart data) / save / duplicate / delete.
- **License note:** PineTS is AGPL-3.0. Fine for this private single-user deployment; if the repo is published or the app is
  offered to others, the project must comply with AGPL-3.0 (or use a commercial PineTS license).

## Development
```bash
cd backend && uv sync --python 3.12 && uv run pytest && uv run ruff check . && uv run mypy app
cd frontend && npm ci && npm run lint && npm run typecheck && npm run build
```

## Later: VPS via Tailscale
1. Install Tailscale on the VPS, enable MagicDNS + HTTPS certificates in the tailnet.
2. `.env`: `PT_SITE_ADDRESS=<host>.<tailnet>.ts.net`, `PT_TLS_MODE=tailscale`,
   `PT_ALLOWED_ORIGINS=https://<host>.<tailnet>.ts.net`.
3. Mount `/var/run/tailscale/tailscaled.sock` into the caddy container and publish 443 only on the
   Tailscale interface IP (never `0.0.0.0`).

## Operations
- Backups: `backups/*.dump` (created by `deploy.sh` before each migration). Restore:
  `docker compose -p powertrade exec -T db pg_restore -U powertrade -d powertrade --clean < backups/<file>.dump`
- Rotate app DB password: change `secrets/db_app_password`, then
  `ALTER ROLE powertrade_app PASSWORD '...'` and redeploy (init script runs only on first DB init).
- Logs: `docker compose -p powertrade logs -f backend worker`
