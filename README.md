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
