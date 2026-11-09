#!/usr/bin/env bash
# Set/replace a single secret without echoing it or leaving it in shell history.
# Usage: ./scripts/set-secret.sh fmp_api_key|telegram_bot_token|telegram_chat_id|anthropic_api_key   (then: ./scripts/deploy.sh)
source "$(dirname "$0")/lib.sh"
name="${1:-}"
case "$name" in
  fmp_api_key) pattern='^[A-Za-z0-9]{16,128}$'; hint="an API key" ;;
  telegram_bot_token) pattern='^[0-9]{5,15}:[A-Za-z0-9_-]{30,64}$'; hint="a bot token (from @BotFather)" ;;
  telegram_chat_id) pattern='^-?[0-9]{1,20}$'; hint="a numeric chat id" ;;
  anthropic_api_key) pattern='^sk-ant-[A-Za-z0-9_-]{20,250}$'; hint="an Anthropic API key (sk-ant-...)" ;;
  *) die "unsupported secret '$name' (allowed: fmp_api_key, telegram_bot_token, telegram_chat_id, anthropic_api_key)" ;;
esac
[[ -d secrets ]] || die "secrets/ missing – run scripts/init-secrets.sh first"
read -rsp "Value for $name: " val; echo
[[ "$val" =~ $pattern ]] || die "value does not look like $hint"
printf '%s' "$val" >"secrets/$name" && chmod 644 "secrets/$name"
unset val
log "secrets/$name updated – run ./scripts/deploy.sh to apply"
