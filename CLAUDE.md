# CLAUDE.md – PowerTrade

Self-hosted TradingView/Aktienfinder-style research app with Claude integration. Single user (owner: Mr. Jarvis).
Read these first: `docs/phase.md` (status & next steps), `docs/features.md` (what exists), `PROMPT.md` (requirements),
`docs/SCORING.md` (formulas), `README.md` (operations), `CHANGELOG.md` (history).

## Working agreement (user preferences – always apply)
- **Reply in German, write code/comments/docs-in-code in English.** Keep answers short.
- **Clarify open questions before building** anything expensive or ambiguous (use multiple-choice questions).
- **Correct the user** when something is wrong (typos in names, wrong file, risky idea) – briefly, then continue.
- Senior-developer mindset with **security first**.
- **At the end of every session: update `CHANGELOG.md`** (steps + features) and `docs/phase.md` (status table).

## Architecture
```
Browser ─HTTPS─> Caddy (tls internal, CSP) ─┬─ /api/*  -> backend  (FastAPI, Python 3.12, uv)
 127.0.0.1:8443                              ├─ /pine-worker.js (own CSP: unsafe-eval, no network)
                                             └─ /*      -> frontend (Next.js 16 standalone, TS)
backend/worker ──> TimescaleDB (pg17) + Redis 8 on internal `data` network (no egress)
worker (ARQ): ingestion (hourly), profiles, fundamentals (weekly), snapshots
```
- DB roles: `powertrade` = owner (migrations only), `powertrade_app` = DML only (API/worker).
- Secrets: Docker secrets from `./secrets/*` (files, never env vars, never in git). Non-secret settings: `.env`.
- Providers: Yahoo (primary prices), Stooq, Kraken, FMP (budgeted 240 calls/day paced, 450 MB/30 d),
  SEC EDGAR (fundamentals, UA contact `PT_SEC_CONTACT`). Test deploys use `PT_PROVIDERS_MODE=fixture` (no network).

## Commands
```bash
./scripts/test-deploy.sh          # isolated stack + smoke tests + migration roundtrip (KEEP=1 keeps it)
./scripts/deploy.sh               # test gate -> build -> backup -> migrate -> rollout -> caddy restart -> verify
./scripts/check-sources.sh        # live provider check from the running worker
./scripts/set-secret.sh fmp_api_key
cd backend  && uv sync --python 3.12 && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd frontend && npm ci && npm run lint && npm run typecheck && npm run build   # build also bundles pine/worker.ts
```
Logs: `docker compose -p powertrade logs -f backend worker` · DB shell: `docker compose -p powertrade exec db psql -U powertrade`

## Definition of Done (every change)
1. Unit tests for new logic (backend `tests/`), smoke test for new endpoints/flows (`tests/smoke/`, run against fixture mode).
2. `ruff`, `ruff format`, `mypy --strict`, `pytest`, frontend `lint`/`typecheck`/`build` green.
3. Runtime-deps import check: `uv sync --no-dev` env must `import app.main, app.worker` (CI does this).
4. `./scripts/test-deploy.sh` green before `./scripts/deploy.sh`.
5. Docs: `CHANGELOG.md`, `docs/phase.md`, `docs/features.md`, README section if user-facing.

## Rules & gotchas learned (do not repeat these bugs)
- **Runtime libraries go into `[project.dependencies]`**, never only into the dev group (httpx incident).
- **asyncpg needs real `date`/`datetime` objects** for date/timestamptz params – never ISO strings.
- **Caddyfile is bind-mounted, admin API off** → config changes need `docker compose restart caddy` (deploy.sh does it).
- Files must be world-readable for non-root containers (Dockerfiles `chmod a+rX`; `scripts/lib.sh` fixes repo perms).
- Docker Desktop "parent snapshot does not exist" → `docker builder prune -af` (cache corruption, not code).
- New tables: migrations run as owner; default privileges grant DML to `powertrade_app` automatically.
- SQL: parameters only; dynamic identifiers only from hard-coded whitelists (e.g. `BAR_TABLES`).
- Provider calls: fixed hosts, `validate_symbol()` before building URLs, size/time limits, no redirects.
  Every FMP call goes through `DailyBudget` (`FmpProvider.get_raw` allow-list).
- SEC EDGAR: per-share values are **split-adjusted by filing date** (`split_adjust`); FY ending Jan–May → previous year.
- Pine Scripts run **only** in the browser worker (PineTS, AGPL-3.0) – never on the server.
  PineTS quirks: no `ta.*` inside ternaries passed to other `ta.*`; no `if`-expression assignment; no variable `type`.
- Frontend: React 19 lint forbids sync `setState` in effects → set state in async callbacks; no inline `confirm()`.
- Lightweight Charts v5: `addSeries(Type, opts, paneIndex)`, markers via `createSeriesMarkers`, fills via `BandFill`.
- Never log URLs with keys (`httpx` logger is WARNING); FMP key is sent as `apikey` header.

## Security baseline (keep)
Argon2id + TOTP login, Redis server-side sessions (revocable), login throttling, Origin/Sec-Fetch-Site CSRF check,
SameSite=Strict/HttpOnly/Secure cookie, strict CSP (no eval outside the Pine worker), read-only containers,
`cap_drop: ALL`, `no-new-privileges`, internal data network, gitleaks + Trivy + pip/npm audit in CI.
Do **not** read or print `secrets/*`, `.secrets-test/*`, `.env` values or `backups/*` unless the user asks.

## Licensing
Repo is MIT, private, single user. PineTS (frontend dep) is AGPL-3.0 → if the repo goes public or the app is offered
to others, AGPL obligations apply (see README).
