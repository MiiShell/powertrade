#!/usr/bin/env bash
# Ephemeral test deployment: builds images, starts an isolated stack (project powertrade-test,
# own volumes, random secrets, no published ports), runs smoke tests + migration roundtrip,
# then tears everything down. KEEP=1 keeps the stack for debugging.
source "$(dirname "$0")/lib.sh"
require docker
require openssl

PROJECT=powertrade-test
SECRETS="$ROOT/.secrets-test"
COMPOSE=(docker compose -p "$PROJECT" --env-file /dev/null -f docker-compose.yml -f docker-compose.test.yml)

export PT_ENV=test PT_SITE_ADDRESS=caddy PT_TLS_MODE=internal PT_ALLOWED_ORIGINS=https://caddy \
  PT_SECRETS_DIR="$SECRETS" PT_ADMIN_USER=admin

cleanup() {
  local rc=$?
  if (( rc != 0 )); then
    log "FAILED – last logs:"
    "${COMPOSE[@]}" logs --tail 40 2>/dev/null || true
  fi
  if [[ "${KEEP:-0}" != 1 ]]; then
    log "tearing down test stack"
    "${COMPOSE[@]}" --profile test --profile tools down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$SECRETS"
  fi
  exit "$rc"
}
trap cleanup EXIT

log "building images"
"${COMPOSE[@]}" --profile test --profile tools build --pull

log "generating ephemeral secrets"
rm -rf "$SECRETS"
SMOKE_ADMIN_PASSWORD="$(rand_secret)"
gen_secrets "$SECRETS" "$SMOKE_ADMIN_PASSWORD" yes admin
SMOKE_TOTP_SECRET="$(cat "$SECRETS/admin_totp_secret")"
export SMOKE_ADMIN_PASSWORD SMOKE_TOTP_SECRET

log "starting db + redis"
"${COMPOSE[@]}" up -d --wait db redis

log "running migrations"
"${COMPOSE[@]}" run --rm migrate

log "starting full stack"
"${COMPOSE[@]}" up -d --wait

log "running smoke tests"
"${COMPOSE[@]}" run --rm smoke

log "migration roundtrip (downgrade base -> upgrade head)"
"${COMPOSE[@]}" run --rm migrate alembic downgrade base
"${COMPOSE[@]}" run --rm migrate alembic upgrade head

log "TEST DEPLOY PASSED"
