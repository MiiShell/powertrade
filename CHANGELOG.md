# Changelog

## Projektstatus & Phasenplan (Stand 2026-11-09)

### Umgesetzte Schritte (Kurzfassung)
1. Planung: `PROMPT.md` (Anforderungen, Architektur, Security), Entscheidungen: Web-App self-hosted (Docker), PostgreSQL + TimescaleDB, Free-Datenquellen → später Paid, Claude Code / Single-User
2. Repo-Hygiene: `.gitignore`, `.gitleaks.toml` (Secret-Scan in CI statt lokalem pre-commit)
3. Spezifikation: `docs/SCORING.md` v0.2 (Aktienfinder-Modell + Pro-Methoden), `docs/REFERENCE_AKTIENFINDER.md`
4. Phase 0: Backend (FastAPI, Auth Argon2id + TOTP, Redis-Sessions, CSRF, Throttling), Worker (ARQ), Frontend (Next.js), Caddy (TLS intern), Compose base/test/prod, Test-Deploy mit Smoke-Tests, Prod-Deploy (Backup → Migration → Rollout → Verify), CI
5. Phase 1: Marktdaten (Yahoo, Stooq, Kraken, FMP mit Tages-/Bandbreiten-Budget), stündlicher Import, Watchlist, Tages-/Wochen-/Monatskerzen
6. UI: Tab-Navigation (Watchlist · Chart · Claude Reports · Status)
7. Phase 2: Chart (Candles, Volumen, SMA/EMA, RSI + Divergenzen, S/R-Linien)
8. Detailseite: Kopfkarte, Firmenprofil (FMP, bereinigt importiert), technische Ratings (11 Oszillatoren + 15 MAs, Tachos, 1T/1W/1M, Snapshots), Pivots (5 Methoden), Saisonalität (Chart + Heatmap)
9. Bugfixes aus Deploy-Läufen: Compose-Interpolation, Dateirechte (0600), fehlende Runtime-Dependency `httpx`, Datumstyp für asyncpg
10. Phase 4: Fundamentaldaten (SEC EDGAR / FMP), 3 Qualitäts-Scores, Ranking, Aktienliste – deployt (Migration 0007)
11. Phase 5: Fair Value Standard (FV-Linien, Bänder, Korridor, Renditerechner), log-lineares Gewinnwachstum – deployt (Migration 0008)
12. Phase 6: Alerts (Regeln, Flanke + Cooldown, Telegram, Historie, Tab) – deployt (Migration 0009)
13. Fair-Value-Widget im Chart; Phase 7: Claude-Chartanalyse (Opus/Sonnet 5.5, Kostenbremse) – deployt (Migration 0010)
14. Phase 8: Claude-Berichte (Tool Use auf DB-Snapshot, Websuche mit Quellen, SVG-Charts, Zahlen-Check, PDF/Markdown) – deployt (Migration 0011)

### Phasenplan
| Phase | Inhalt | Status |
|---|---|---|
| 0 | Grundgerüst, Auth, Docker, Test-/Prod-Deploy, CI | ✅ erledigt, lokal deployt |
| 1 | Datenmodell, Provider-Adapter, Import (inkl. FMP) | ✅ erledigt |
| 2 | Charting: Candles, SMA/EMA/RSI, Divergenzen, S/R-Linien | ✅ erledigt |
| 3 | Saisonalität | ✅ erledigt (Teil der Detailseite) |
| – | Detailseite (Technicals, Pivots, Profil, Kennzahlen) | ✅ erledigt, im Browser geprüft (BTC-Signale vs. TradingView: 25/26 → mit Ichimoku-Fix 26/26 erwartet) |
| – | Chart-Widgets (Spannen), RSI optional, Pine Scripts (PineTS) + Editor | ✅ erledigt, im Browser geprüft |
| 4 | Fundamentaldaten-Import, Aktienliste, Qualitäts-Scores (3 Profile) + Ranking | ✅ deployt, Browser-Check offen |
| 5 | Fair-Value-Engine Standard, Bewertungslinien, Prognosekorridor, Renditerechner | ✅ deployt, Browser-Check offen |
| 5b | Fair Value Pro-Methoden (KBV, DCF, Graham, DDM) | ⏳ offen |
| 6 | Alerts (Preis, %-Änderung, MA-Cross, RSI, Fair Value) via Telegram + In-App | ✅ deployt, Telegram-Secrets offen |
| 6b | Alerts per E-Mail / Web-Push | ⏳ offen |
| 7 | Claude-Chartanalyse auf Anfrage | ✅ deployt, API-Key offen |
| 8 | Claude-Berichte (Abilitato-Stil), PDF-Export, Kostenbremse | ✅ deployt, API-Key offen |
| 9 | Kreuzreferenzen: ETF-Overlap, Sektor-Exposure, Korrelation, Beziehungsgraph | ⏳ offen |
| 10 | Hardening, Security-Review, Backups, Paid-Provider-Switch, VPS via Tailscale | ⏳ offen |

### Offene Punkte / Technische Schulden
- Docker-Images auf Digests pinnen (timescaledb, redis, caddy)
- CSP: `'unsafe-inline'` durch Nonces ersetzen
- TOTP-Replay-Schutz (Code nur einmal pro Zeitfenster)
- Backups verschlüsseln (`backups/*.dump`), Restore-Test automatisieren
- Krypto-Marktkapitalisierung/Profil (Quelle z. B. CoinGecko)
- Intraday-Timeframes (aktuell nur Tageskerzen)
- `system_check.nonce`: `varchar` → `text` (Timescale-Hinweis)
- Technical Ratings: weitere Stichproben gegen TradingView (andere Assets/Timeframes)
- Pine: Tabellen/Labels/Lines/Boxes rendern; `input()`-Werte im UI änderbar machen
- Live-Quellen prüfen: `./scripts/check-sources.sh` (insb. FMP-Abdeckung im Free-Plan)

---

## 2026-11-08 — Planning session
### Decisions
- Platform: self-hosted web app (Docker Compose) instead of Electron
- Database: PostgreSQL + TimescaleDB (relational cross-references + time series)
- Data: free sources first, optional paid provider (FMP/EODHD) later via adapter switch
- Target: Claude Code, single user (auth mandatory)
### Added
- `PROMPT.md`: build prompt incl. features (charting SMA/EMA/RSI/seasonality, scorecard, fair value, alerts, Claude chart analysis, Abilitato-style reports), data model, sources, security requirements, phases, Definition of Done
- `.gitignore`: secrets (.env, keys, certs), Python, Node/Next.js, Docker volumes, DB dumps/backups, logs, OS/editor files
- `.pre-commit-config.yaml`: gitleaks v8.30.1 + pre-commit-hooks v6.0.0 (detect-private-key, large files, merge conflicts, yaml, whitespace)
- `.gitleaks.toml`: default ruleset, allowlist for `.env.example`
### Changed
- Local pre-commit hook dropped (Homebrew build fails on Intel Mac); secret scanning moved to CI (gitleaks GitHub Action). `.pre-commit-config.yaml` kept as optional.
### Added
- `docs/SCORING.md` v0.1: scorecard (5 criteria, 0–15 pts), fair-value methods (P/E & P/B history, 2-stage DCF, Graham, DDM), sector weight profiles, margin of safety, data rules, test requirements
- `PROMPT.md`: F2/F3 reference `docs/SCORING.md`
- `docs/REFERENCE_AKTIENFINDER.md`: extracted feature reference (tabs, 3-profile scorecard with scales, ranking, fair-value chart & bands, Qualitätscheck charts, ETF tab, list columns, data requirements)
### Changed
- `docs/SCORING.md` v0.2: Aktienfinder-style standard (3 quality profiles 1–10, ranking 0–100, multiple-based FV with bands/corridor/return calculator) + Pro methods (P/B, DCF, Graham, DDM, blend)
- `PROMPT.md`: F2/F3 rewritten accordingly

## 2026-11-09 — Phase 0: scaffold, test deployment, production deployment
### Added
- `backend/`: FastAPI app (health/ready, auth, system selfcheck), settings with Docker-secret `_FILE` support and prod validation, Argon2id + TOTP auth, revocable Redis sessions, login throttling, CSRF origin check, ARQ worker (heartbeat, ping job), Alembic migration 0001 (TimescaleDB extension, `system_check` hypertable + retention), admin CLI, unit tests (14), ruff/mypy strict clean, multi-stage non-root Dockerfile
- `frontend/`: Next.js 16 (standalone) login + system status + selfcheck page, ESLint/TS strict, non-root Dockerfile
- `docker-compose.yml` (+ `.test.yml`, `.prod.yml`): TimescaleDB, Redis (password, non-root), migrate (tools profile), backend, worker, frontend, Caddy; internal `data` network, read-only FS, cap_drop ALL, no-new-privileges, Docker secrets
- `infra/caddy`: TLS (internal CA now, Tailscale-ready), security headers/CSP, body limit, internal healthz; `infra/db/10-roles.sh`: least-privilege app role
- `tests/smoke`: 16 end-to-end smoke tests via Caddy with verified TLS
- `scripts/`: `init-secrets.sh`, `test-deploy.sh` (isolated ephemeral stack + smoke + migration roundtrip), `deploy.sh` (test gate → backup → migrate → rollout → verify)
- `.github/workflows/ci.yml`: backend/frontend checks, gitleaks, Trivy, test-deploy job
- `README.md`, `.env.example`
### Changed
- `PROMPT.md`: auth + platform decisions; `.gitignore`: `.secrets-test/`, `_to_delete/`
### Not yet verified
- ~~Docker stack not executed~~ → test deploy passed 2026-11-09
- Fix: `docker-compose.test.yml` no longer requires `SMOKE_ADMIN_PASSWORD` at build time (set after image build); smoke tests fail fast if empty
- Fix: host files created with 0600 were unreadable for non-root containers (alembic PermissionError on pyproject.toml): Dockerfiles normalize permissions, `scripts/lib.sh` makes repo files world-readable (secrets excluded)
- Verified: `scripts/test-deploy.sh` passed on Mac (all smoke tests + migration roundtrip)
- Verified: production deploy (`scripts/deploy.sh`) running at https://localhost:8443 – login, readiness (db/redis/worker) and selfcheck OK (~512 ms)

## 2026-11-09 — Phase 1: market data layer (daily + weekly)
### Added
- Migration `0002`: `instrument`, `instrument_source` (provider priority), `watchlist`/`watchlist_item`, `price_bar_1d` hypertable (checks, compression after 180 d), `price_bar_1w` view (Monday buckets), `ingestion_run`; seed watchlist "Standard" (NVDA, BTC, ETH, SOL, XMR, Gold GC=F, Silver SI=F)
- `app/market/providers.py`: Yahoo, Stooq, Kraken adapters (fixed hosts, symbol allowlist regex, 10 MB/20 s limits, per-provider rate limit, no redirects) + deterministic `FixtureProvider`
- `app/market/ingest.py`: provider fallback, incremental fetch (7-day overlap), sanitation (invalid/future bars, high/low repair, dedupe), batched idempotent upsert, run logging
- Worker: `ingest` job, hourly `schedule_ingestion` cron (dedup job ids)
- API (`app/routes/market.py`): watchlist read/add/remove, manual refresh, bars (1d/1w, range, limit ≤ 10 000), ingestion runs; strict input validation
- Frontend: watchlist table (price, change %, date, import status, refresh/remove, add form)
- Tests: 23 new unit tests (parsers, sanitation, SSRF/symbol validation, HTTP errors, fixture determinism); smoke `test_ingestion.py` (auth, seeded ingest, 1d/1w integrity, add/refresh idempotency/remove, validation); shared `conftest.py`
- `scripts/check-sources.sh`: live provider check from the worker container
- Settings: `PT_PROVIDERS_MODE` (live|fixture), `PT_HTTP_USER_AGENT`; test deploy runs in fixture mode

## 2026-11-09 — Financial Modeling Prep integration
### Added
- `FmpProvider` (stable `historical-price-eod/full`, key via `apikey` header, 402/401/429 handling, 5-year history cap)
- `app/market/budget.py`: Redis `DailyBudget` – atomic Lua reservation, daily cap 240 paced over the day (burst 20), rolling 30-day bandwidth cap 450 MB, block-for-today on HTTP 429, usage stats
- Migration `0003`: provider `fmp` allowed; FMP added as priority-2 source for stocks/ETFs (Stooq → 3)
- API `GET /api/providers/usage`; status panel shows FMP calls/bandwidth
- Secret `fmp_api_key` (Docker secret, optional): `scripts/set-secret.sh`, prompt in `init-secrets.sh`, auto-created empty in `deploy.sh`
- `check-sources.sh` checks FMP; tests: 7 new unit tests (budget pacing/caps/block, header auth, history cap, error mapping), smoke test for FMP source + usage
### Security
- API key never in URL, env or logs (`httpx` logger set to WARNING)
- Fix: `httpx` was only a dev dependency → worker crashed in container (ModuleNotFoundError); now a runtime dependency, verified by importing app with prod-only deps

## 2026-11-09 — UI: tab navigation
### Added
- `frontend/app/shell.tsx`: top bar with tabs **Watchlist · Chart · Claude Reports · Status** (ARIA tablist, URL hash `#watchlist|#chart|#reports|#status` → reload/back keep the tab), user + logout in the top bar
- Click on a watchlist symbol opens the Chart tab for that instrument (placeholder until Phase 2); Claude Reports placeholder (Phase 7/8)
### Changed
- Status panel (system status, FMP budget, selfcheck) moved to `frontend/app/status.tsx` / Status tab

## 2026-11-09 — Phase 2: charting
### Added
- `app/market/indicators.py`: SMA, EMA (SMA seed), RSI (Wilder), pivots, regular RSI divergences; 7 unit tests (StockCharts reference data, edge cases)
- `GET /api/instruments/{id}/chart`: bars + indicators with warm-up history, RSI + divergences, levels; validated periods (≤ 6, 2–500)
- Migration `0004`: `chart_level` (price/color/label checks); `POST/DELETE /api/instruments/{id}/levels` (max 50)
- Frontend `app/chart.tsx`: Lightweight Charts v5 – candles, volume, SMA/EMA lines, RSI pane (30/50/70, divergence lines + BULL/BEAR markers), 1T/1W, ranges, OHLC legend, instrument picker, click-to-place S/R lines with colors, indicator settings in localStorage
- Tab routing `#chart/<id>`; watchlist symbol opens its chart
- Smoke tests: chart indicators/warm-up/RSI bounds, validation, levels CRUD

## 2026-11-09 — Asset details page + UI review
### Added
- Backend: `app/market/technicals.py` (RSI, Stoch, CCI, ADX, AO, Momentum, MACD, StochRSI, Williams %R, Bull Bear Power, Ultimate Osc.; EMA/SMA 10–200, Ichimoku base, VWMA, HMA; TradingView-style ratings), `app/market/analytics.py` (pivots ×5, seasonality, key stats), `app/market/profile.py` (FMP profile cleaning), `app/market/details.py` (DB services, snapshot persistence, profile import)
- Migration `0005`: `price_bar_1mo` view, `instrument_profile`, `technical_snapshot`
- API: `GET /api/instruments/{id}/details`, `GET /api/instruments/{id}/seasonality`, `POST /api/instruments/{id}/profile/refresh`
- Worker: `profile` job (weekly, ≤ 5/h, FMP-budgeted), technical snapshots after every successful ingest
- Frontend `app/details.tsx`: header card (volume / day / 52-week bars), company profile, gauges + oscillator/MA tables (1D/1W/1M), pivot table, seasonality chart (years, average, year range) + monthly heatmap; Chart/Details toggle; ⓘ button in watchlist
- Tests: 14 new unit tests (pivots vs. TradingView example, seasonality, stats, technicals, profile cleaning); smoke `test_ingestion_details.py`
### Fixed (UI review in browser)
- Default 1-year range now applied after layout; RSI pane enlarged; price-scale labels show MA values instead of names
- Fix: technical snapshot insert failed (asyncpg rejects ISO strings for date/timestamptz params) → pass a timezone-aware `datetime`; replaced deprecated `HTTP_422_UNPROCESSABLE_ENTITY`

## 2026-11-09 — Browser review of details page
### Verified
- Details page live with real data: NVDA profile imported from FMP (cleaned), technicals 1D/1W/1M, pivots, seasonality (NVDA 2022 −50 %, 2023 +239 % plausible)
- BTC 1D vs. TradingView screenshot: oscillators 11/11 identical signals; MAs 14/15 (values within ~0.1 %, Yahoo vs. Coinbase data); pivots within ~0.02 %
### Fixed
- Ichimoku rating now also requires a bullish/bearish cloud (lead 1 vs. lead 2) like TradingView → was the only differing signal
- Chart price axis formatted de-DE (thousands separators); buttons no longer wrap

## 2026-11-09 — Chart widgets, optional RSI, Pine Scripts
### Added
- Chart: widget row above the chart (price/volume, day range, week range, 52-week range); `GET /api/instruments/{id}/stats`; `range_week` in key stats
- Indicator menu: built-in RSI + divergences optional (toggle), Pine Scripts toggleable, choice stored in browser
- Pine runtime: PineTS 0.13.1 in sandboxed Web Worker (`frontend/pine/worker.ts` → `public/pine-worker.js` via esbuild), 10 s timeout, serialised runs; rendering of `plot` (per-bar colours, hidden plots), `hline`, `fill` (custom `BandFill` series primitive)
- Caddy: separate CSP for `/pine-worker.js` (`'unsafe-eval'`, `connect-src 'none'`); app CSP unchanged (no eval) + `worker-src 'self'`
- Migration `0006`: `pine_script` (name unique, ≤ 100 KB, built-in flag) + seeded built-ins `[Hoss] OBV RSI` (v4 → v5) and `[Hoss] VWAP Deviation`
- API: `GET/POST /api/pine/scripts`, `PUT/DELETE /api/pine/scripts/{id}` (built-ins read-only, version check //@version=5|6)
- Pine editor modal (new from template, edit, test run on current data, save, duplicate, two-step delete)
- Tests: 7 unit tests (script validation), smoke `test_pine.py` (auth, built-ins, CRUD/validation, worker CSP isolation, range widgets); worker bundle verified in Node: OBV RSI equals independent JS reference (42.8105)
### Notes
- PineTS bugs found + worked around in the Hoss scripts: nested `ta.*` inside ternary arguments → NaN; `if`-expression assignment → na
- License: PineTS is AGPL-3.0 (OK for private use; see README)
- Fix: `deploy.sh` restarts Caddy after rollout (bind-mounted Caddyfile, no admin API → config changes were not applied); chart range widgets re-laid out (label above values)

## 2026-11-09 — Browser verification: Pine Scripts
### Verified
- Worker served with isolated CSP (`'unsafe-eval'`, `connect-src 'none'`) after Caddy restart
- `[Hoss] VWAP Deviation`: basis + dev-2 lines and both band fills render on the price chart (BTC)
- `[Hoss] OBV RSI`: own pane with per-bar colours (red ≥ 70, green ≤ 30)
- Editor: template test run OK, save (auto-enabled in chart), two-step delete; test script removed afterwards
### Changed
- Editor button row left-aligned

## 2026-11-09 — Phase 4: fundamentals, quality scores, ranking
### Decisions
- Sources: SEC EDGAR (US, long history) + FMP fallback; SEC contact = account e-mail (`PT_SEC_CONTACT` in `.env`, sent only to sec.gov); universe = watchlist stocks
### Added
- Migration `0007`: `fundamental_fact` (annual, long format), `corporate_action` (splits), `fundamentals_run`, `score_snapshot`, `ranking_strategy` (default "Standard")
- `SecProvider` (ticker map cached 7 d in Redis, companyfacts, fair-access UA, 80 MB cap), FMP `get_raw` with endpoint allow-list (statements, dividends, profile), Yahoo split history
- `app/market/fundamentals.py`: EDGAR/FMP parsing + cleaning, split adjustment by filing date, upsert (SEC beats FMP), weekly refresh job (≤ 10/h)
- `app/market/scores.py`: signed-R² stability, trendline CAGR, payback years, annual FV_std + discount, 3 profile scores, ranking 0–100
- API: `GET /api/stocks`, `GET /api/instruments/{id}/scorecard`, `POST /api/instruments/{id}/fundamentals/refresh`, `GET/PUT /api/ranking/strategy`
- UI: tab „Aktienliste“ (sortable, score badges, ranking bars, strategy editor); details page: Aktienfinder-style scorecard (10-segment bars), ranking Soll/Ist, 10-year fundamentals table
- Tests: 12 new unit tests (EDGAR filtering/restatements, split adjustment, Yahoo splits, FMP parsing, scores, ranking); smoke `test_stocks.py`

## 2026-11-09 — Handover to Claude Code
### Added
- `CLAUDE.md`: working agreement (German replies, English code, clarify first, correct user, changelog per session), architecture, commands, Definition of Done, learned gotchas, security baseline
- `.claude/settings.json`: allow common test/lint/log commands, ask for deploy/commit/push/prune, deny reading secrets/.env/backups
- `docs/features.md`: feature inventory with status + API overview
- `docs/phase.md`: phase status, concrete next steps (finish Phase 4 deploy, Phase 5 fair value, Phase 6 alerts), tech debt
- `.gitignore`: `.claude/settings.local.json`

## 2026-11-09 — Phase 4 deployment
### Fixed
- Smoke tests: the login rate-limit test ran before the new `test_stocks.py` (alphabetical file order) and
  throttled all later logins (429). It is now marked `run_last`; `tests/smoke/conftest.py` sorts such tests to
  the end independent of file names.
### Deployed
- `./scripts/test-deploy.sh` green (39 smoke tests, migration roundtrip), `./scripts/deploy.sh` with backup,
  migration `0007`, readiness ok.
### Verified (live)
- `fundamentals_run`: NVDA `source=sec`, `status=success`, 218 facts.
- NVDA diluted EPS split-adjusted without jumps at the 2021 (4:1) and 2024 (10:1) splits; median P/E 50.5;
  FV_std 247 USD; payback years 0 (net cash).
### Known issue
- Earnings-growth criterion is N/A (0 points) for NVDA: the linear EPS trendline starts <= 0 for exponential
  growth. Behaviour matches SCORING.md §8; a log-linear fit is proposed (decision pending).

## 2026-11-09 — Phase 5: fair value (standard model)
### Added
- `app/market/fairvalue.py`: daily-stepped multiples (KGV, KCV, KUV, dividend yield), medians over 5/8/10/15/20 y/all,
  FV lines (earnings adjusted = FV_std, cash flow, revenue, dividend), ±10 % bands, buy limit (MoS 20 %), 3-year
  trend corridor (growth clamped ±20 %), expected return p.a., yearly multiples table, weekly price series.
- Migration `0008`: `fair_value_setting` (period + user-overridden average multiples per stock).
- API: `GET /api/instruments/{id}/fairvalue?period=`, `PUT /api/instruments/{id}/fairvalue/settings` (validated).
- UI: panel „Fairer Wert“ on the details page (chart, period switch, line switch, editable averages, yearly table,
  purchase calculator); stock list columns „Abstand FV“ and „Rendite FV p.a.“.
- Tests: `tests/test_fairvalue.py` (stepping, limits, lines, overrides, corridor cap, expected return), smoke tests
  for the endpoints/settings/auth.
### Changed
- TrendGrowth: log-linear fit when all values > 0 (linear fallback). NVDA earnings growth 10 y: N/A → 56.8 %,
  earnings-growth score 5 → 7.
- Score criterion Discount uses FV_std of the engine; the annual approximation `fair_value_std` was removed.
- `docs/SCORING.md` v0.3 (section 8b implementation notes).
### Deployed
- Test deploy green (41 smoke tests, migration roundtrip incl. 0008), `deploy.sh` with backup, readiness ok.

## 2026-11-09 — Fair value chart widget
### Added
- Chart view widget „Fairer Wert“ (stocks only): FV_std, distance to price, position within the ±50 % bands, buy
  limit, expected return; click opens the details page.
- API `GET /api/instruments/{id}/fairvalue/summary` (small payload; `{"available": false}` without fundamentals).

## 2026-11-09 — Phase 6: alerts (Telegram + in-app)
### Added
- Migration `0009`: `alert` (rule, params, cooldown, edge state) and `alert_event` (history, delivery status, read).
- `app/market/alerts.py`: param validation, conditions (price above/below, % change over N days, SMA/EMA cross,
  RSI above/below, fair-value distance), edge trigger + cooldown, plain-text messages, DB layer.
- `app/market/notify.py`: Telegram Bot API notifier (fixed host, no redirects, size/time limits, token never in
  logs or stored errors), fixture notifier for test deployments, null notifier when not configured.
- Worker: evaluation after every successful ingestion, jobs `alerts` (evaluate now) and `telegram_test`;
  Telegram status in Redis (`pt:telegram:status`, never the token).
- API `/api/alerts` (CRUD, events, mark read, Telegram test, max. 1/min); UI tab „Alerts“ with unread badge.
- Secrets `telegram_bot_token` / `telegram_chat_id` (worker only), `set-secret.sh` validates both formats.
- Tests: `tests/test_alerts.py` (validation, conditions, edge/cooldown, messages, Telegram mock incl. token
  hiding), smoke `tests/smoke/test_alerts.py` (fire once, delivery, MA-cross arming, history, auth).
### Deployed
- Test deploy green (46 smoke tests, migration roundtrip incl. 0009), `deploy.sh` with backup, readiness ok.
  Telegram not yet configured (empty secrets created) → alerts are in-app only until the secrets are set.

## 2026-11-09 — Phase 7: Claude chart analysis
### Added
- `app/market/ai.py`: official `anthropic` SDK (2.6, runtime dependency), streaming Messages call with chart PNG +
  JSON context, adaptive thinking, effort `high`, structured output (`output_config.format` JSON schema, validated
  again with Pydantic), server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`),
  refusal/max_tokens/invalid-output handling, typed error chain, cost from `usage` (priced by the served model).
- `app/market/chart_analysis.py`: context from the DB only (bars, indicators, divergences, own lines, pivots,
  technical rating, stats, seasonality, fair value), budget guard (monthly USD incl. reservations of pending runs,
  daily count, advisory lock), worker run, history, stale-run expiry (cron every 10 min).
- Migration `0010`: `chart_analysis`, `ai_call_log`.
- API: `POST /api/instruments/{id}/analysis` (strict PNG validation: magic bytes, IHDR size, 700 KB),
  `GET /api/analyses/{id}`, `GET /api/instruments/{id}/analyses`, `GET /api/ai/usage`.
- UI: panel „Claude-Chartanalyse“ below the chart (model choice, cost estimate, budget, result with key levels
  → „+ Linie“, scenarios, history).
- Secret `anthropic_api_key` (worker only, `set-secret.sh` validates `sk-ant-…`), `.env` `PT_AI_MONTHLY_BUDGET_USD`,
  `PT_AI_DAILY_LIMIT`; fixture analyzer for test deployments (no network).
- Tests: `tests/test_ai.py` (PNG checks, pricing, schema ↔ model, request shape, refusal, max_tokens, invalid output,
  fallback pricing), smoke `tests/smoke/test_analysis.py` (validation, worker flow, cost log, usage, crypto).
### Deployed
- Test deploy green (50 smoke tests, migration roundtrip incl. 0010), `deploy.sh` with backup, readiness ok.
  API key not set yet (analyzer `none`); the live API path is covered by mocked-SDK unit tests only.

## 2026-11-09 — Phase 8: Claude stock reports
### Added
- `app/market/report_data.py`: DB snapshot per report (instrument, profile, market stats, 10 fiscal years with
  margins/growth/FCF/net debt/BVPS/P/B/payout/share change, CAGRs, yearly prices, max drawdown, fair value, P/B vs.
  median, scores, technical rating, DB source info).
- `app/market/report_agent.py`: manual tool-use loop (Messages API, streaming, adaptive thinking, effort `high`,
  prompt caching, server-side refusal fallback), client tools bound to the snapshot (no arguments), server-side web
  search (`web_search_20260209`, max 6), strict `submit_report` tool validated with Pydantic, `pause_turn`
  handling, one nudge if no report, per-report cost cap (1.50 USD, checked before every turn), heuristic number
  check (German number formats, Mrd./Mio./%, "(extern)" exemption).
- `app/market/report_charts.py`: dependency-free SVG charts (revenue/earnings/FCF, margins, EPS/DPS, balance sheet,
  price vs. fair value), all text escaped, delivered as data URIs (`<img>`, no script context).
- `app/market/reports.py`: versioned storage, shared budget guard (reservations of analyses + reports), worker run,
  `ai_call_log` entry per report, Markdown export, stale-run expiry.
- Migration `0011`: `report`. API: `POST /api/instruments/{id}/reports`, `GET /api/reports`, `GET /api/reports/{id}`,
  `GET /api/reports/{id}/markdown`.
- UI: tab „Claude Reports“ (create, version list with cost and warnings, report view with tables/charts, flagged
  numbers, verified sources, print/PDF layout, Markdown download).
- Tests: `tests/test_reports.py` (annual table, number check, tool payloads, SVG escaping, agent loop incl. parallel
  tool results, `pause_turn`, nudge, cost cap, invalid submit, Markdown), smoke `tests/smoke/test_reports.py`.
### Changed
- Shared AI budget default 10 → 25 USD/month (`PT_AI_MONTHLY_BUDGET_USD`), new `PT_AI_REPORT_DAILY_LIMIT` (5).
- Fixed: `fmt_num` turned the unit "Mrd." into "Mrd," (found by the new unit test).
- ruff: German typographic characters (–, −) allowed in strings.
### Deployed
- Test deploy green (53 smoke tests, migration roundtrip incl. 0011), `deploy.sh` with backup, readiness ok.
  API key not set yet; the live agent path is covered by mocked-SDK unit tests only.

