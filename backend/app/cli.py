"""Admin helpers. Usage:
python -m app.cli hash-password   (reads password from stdin)
python -m app.cli gen-totp [user] (prints secret + otpauth URI)
python -m app.cli gen-secret [bytes]
"""

import secrets
import sys

import pyotp

from app.security import hash_password


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "hash-password":
        pw = sys.stdin.readline().rstrip("\n")
        if len(pw) < 12:
            print("password must be >= 12 chars", file=sys.stderr)
            return 2
        print(hash_password(pw))
    elif cmd == "gen-totp":
        user = argv[2] if len(argv) > 2 else "admin"
        secret = pyotp.random_base32()
        print(secret)
        print(pyotp.TOTP(secret).provisioning_uri(name=user, issuer_name="PowerTrade"), file=sys.stderr)
    elif cmd == "gen-secret":
        print(secrets.token_urlsafe(int(argv[2]) if len(argv) > 2 else 48))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
