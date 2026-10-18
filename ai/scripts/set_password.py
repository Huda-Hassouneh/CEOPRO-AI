"""
Set (or reset) a KEEL account's password from the server, without email.

For the account owner running KEEL themselves (a Codespace, a local stack)
before an email service is configured - the normal "forgot password" flow
needs one to deliver its code.

    cd backend && set -a && . ./.env && set +a
    python -m scripts.set_password --email you@example.com

The password is typed at a hidden prompt (twice), checked against the same
rules as signup, stored only as its bcrypt hash through the same database
function the reset flow uses (connecting as the restricted application
role), and never printed or logged. It is never accepted as a command-line
argument, which would leave it in shell history and process listings.

--mark-verified also marks the email address confirmed - only for your own
address, since this skips proving you can receive mail there.
"""
import argparse
import getpass
import sys

from fastapi import HTTPException

from src.ai import db
from src.ai.core import auth_throttle
from src.ai.core.security import ensure_password_policy, hash_password


def set_password(email: str, new_password: str, mark_verified: bool = False) -> bool:
    """True when the account exists and its password was changed."""
    conn = db.auth_lookup_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM auth_lookup_user_by_email(%s);", (email,))
            row = cursor.fetchone()
            if row is None:
                return False
            user_id = row[0]
            cursor.execute("SELECT auth_reset_password(%s, %s);", (user_id, hash_password(new_password)))
            if mark_verified:
                cursor.execute("SELECT auth_mark_email_verified(%s);", (user_id,))
        conn.commit()
    finally:
        conn.close()
    try:
        auth_throttle.reset("login", email)  # a fresh password starts with a clean slate
    except Exception:  # noqa: BLE001 - throttling store unavailable; not fatal here
        pass
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--mark-verified", action="store_true")
    args = parser.parse_args(argv)

    first = getpass.getpass("New password: ")
    try:
        ensure_password_policy(first)
    except HTTPException as err:
        print(err.detail, file=sys.stderr)
        return 2
    if getpass.getpass("Repeat it: ") != first:
        print("The two passwords don't match. Nothing was changed.", file=sys.stderr)
        return 2
    if not set_password(args.email.strip(), first, args.mark_verified):
        print("No account uses that email address. Nothing was changed.", file=sys.stderr)
        return 1
    print("Password updated. Sign in with the new password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
