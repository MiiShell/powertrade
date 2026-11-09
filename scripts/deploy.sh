#!/usr/bin/env bash
# Production deploy (local, https://localhost:<PT_HTTPS_PORT>).
# Order: test deploy must pass -> backup -> migrate -> rollout -> verify.
source "$(dirname "$0")/lib.sh"
require docker
require curl

[[ -f .env ]] || die ".env missing – run scripts/init-secrets.sh"
[[ -s secrets/session_secret ]] || die "secrets missing – run scripts/init-secrets.sh"
if [[ ! -f secrets/fmp_api_key ]]; then
  : >secrets/fmp_api_key && chmod 644 secrets/fmp_api_key
  log "created empty secrets/fmp_api_key – set it with: ./scripts/set-secret.sh fmp_api_key"
fi
for opt in telegram_bot_token telegram_chat_id; do
  if [[ ! -f "secrets/$opt" ]]; then
    : >"secrets/$opt" && chmod 644 "secrets/$opt"
    log "created empty secrets/$opt – Telegram alerts: ./scripts/set-secret.sh $opt"
  fi
done
# shellcheck disable=SC1091
set -a; source .env; set +a
unset PT_SECRETS_DIR

PROJECT=powertrade
COMPOSE=(docker compose -p "$PROJECT" --env-file .env -f docker-compose.yml -f docker-compose.prod.yml)
PORT="${PT_HTTPS_PORT:-8443}"

log "step 1/5: test deployment"
"$ROOT/scripts/test-deploy.sh"

log "step 2/5: build images"
"${COMPOSE[@]}" --profile tools build

log "step 3/5: start db + redis, backup"
"${COMPOSE[@]}" up -d --wait db redis
mkdir -p backups && chmod 700 backups
if "${COMPOSE[@]}" exec -T db psql -U powertrade -d powertrade -tAc \
  "SELECT 1 FROM information_schema.tables WHERE table_name='alembic_version'" | grep -q 1; then
  f="backups/powertrade-$(date +%Y%m%d-%H%M%S).dump"
  "${COMPOSE[@]}" exec -T db pg_dump -U powertrade -Fc powertrade >"$f"
  chmod 600 "$f"
  log "backup written: $f"
else
  log "fresh database – no backup needed"
fi

log "step 4/5: migrate + rollout"
"${COMPOSE[@]}" run --rm migrate
"${COMPOSE[@]}" up -d --wait --remove-orphans
# Caddyfile is a bind mount (admin API disabled -> no hot reload): restart so config changes take effect
"${COMPOSE[@]}" restart caddy >/dev/null
"${COMPOSE[@]}" up -d --wait caddy

log "step 5/5: verify"
"${COMPOSE[@]}" cp caddy:/data/caddy/pki/authorities/local/root.crt secrets/caddy-root.crt >/dev/null
curl --fail --silent --show-error --cacert secrets/caddy-root.crt "https://localhost:${PORT}/api/health/ready"
echo
log "DEPLOYED: https://localhost:${PORT}"
log "Trust the local CA once (removes browser warning):"
echo "  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain secrets/caddy-root.crt"
