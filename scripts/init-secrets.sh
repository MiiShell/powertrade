#!/usr/bin/env bash
# Creates production secrets in ./secrets (gitignored). Refuses to overwrite existing secrets.
source "$(dirname "$0")/lib.sh"
require docker
require openssl

DIR="$ROOT/secrets"
[[ -s "$DIR/session_secret" ]] && die "secrets already exist in $DIR (refusing to overwrite)"
[[ -f .env ]] || { cp .env.example .env; log "created .env from .env.example"; }
# shellcheck disable=SC1091
set -a; source .env; set +a

log "building backend image (needed for password hashing)"
build_backend

read -rsp "Admin password (min. 12 chars): " pw; echo
read -rsp "Repeat: " pw2; echo
[[ "$pw" == "$pw2" ]] || die "passwords do not match"
(( ${#pw} >= 12 )) || die "password too short"
read -rp "Enable TOTP 2FA? [Y/n] " t
[[ "${t:-Y}" =~ ^[Yy]$ ]] && totp=yes || totp=no

log "generating secrets"
gen_secrets "$DIR" "$pw" "$totp" "${PT_ADMIN_USER:-admin}"
unset pw pw2
if [[ "$totp" == yes ]]; then
  log "TOTP secret (add to your authenticator app):"
  cat "$DIR/admin_totp_secret"
fi
log "done – secrets in $DIR"
