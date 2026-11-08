# Changelog

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
