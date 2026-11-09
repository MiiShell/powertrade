#!/usr/bin/env bash
# Set/replace a single secret without echoing it or leaving it in shell history.
# Usage: ./scripts/set-secret.sh fmp_api_key   (then: ./scripts/deploy.sh)
source "$(dirname "$0")/lib.sh"
name="${1:-}"
case "$name" in
  fmp_api_key) ;;
  *) die "unsupported secret '$name' (allowed: fmp_api_key)" ;;
esac
[[ -d secrets ]] || die "secrets/ missing – run scripts/init-secrets.sh first"
read -rsp "Value for $name: " val; echo
[[ "$val" =~ ^[A-Za-z0-9]{16,128}$ ]] || die "value does not look like an API key"
printf '%s' "$val" >"secrets/$name" && chmod 644 "secrets/$name"
unset val
log "secrets/$name updated – run ./scripts/deploy.sh to apply"
