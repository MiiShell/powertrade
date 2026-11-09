# shellcheck shell=bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Repo files must be world-readable (containers run as non-root / read bind mounts).
# Secrets dirs are excluded and stay private (700).
find . \( -path ./.git -o -path ./secrets -o -path ./.secrets-test -o -path ./backups -o -path ./_to_delete \
  -o -name node_modules -o -name .venv \) -prune -o -exec chmod go+rX,go-w {} + 2>/dev/null || true

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || die "'$1' is not installed"; }

rand_secret() { openssl rand -base64 64 | tr -dc 'A-Za-z0-9' | cut -c1-48; }

build_backend() { docker build -q -t powertrade-backend:local ./backend >/dev/null; }

# gen_secrets <dir> <admin_password> <totp:yes|no> [admin_user]
gen_secrets() {
  local dir="$1" admin_pw="$2" totp="$3" user="${4:-admin}"
  mkdir -p "$dir" && chmod 700 "$dir"
  local n
  for n in db_owner_password db_app_password redis_password; do rand_secret >"$dir/$n"; done
  printf '%s%s' "$(rand_secret)" "$(rand_secret)" >"$dir/session_secret"
  printf '%s\n' "$admin_pw" | docker run --rm -i --network none powertrade-backend:local \
    python -m app.cli hash-password >"$dir/admin_password_hash"
  if [[ "$totp" == yes ]]; then
    docker run --rm --network none powertrade-backend:local python -m app.cli gen-totp "$user" \
      >"$dir/admin_totp_secret"
  else
    : >"$dir/admin_totp_secret"
  fi
  [[ -f "$dir/fmp_api_key" ]] || : >"$dir/fmp_api_key"   # optional, set via scripts/set-secret.sh
  # Readable by container users (postgres, redis, uid 10001); directory stays private.
  chmod 644 "$dir"/*
}
