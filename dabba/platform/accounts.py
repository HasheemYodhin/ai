"""Manage an existing Dabba account from the server host."""

import argparse
from getpass import getpass

from dabba.platform.core import utc_ms
from dabba.platform.services import IdentityService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--role", choices=("admin", "member"))
    action.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()

    identity = IdentityService()
    email = args.email.strip().lower()
    account = identity.store.fetchone("SELECT id FROM users WHERE email=?", (email,))
    if not account:
        parser.error("No account exists for that email")
    user_id = account["id"]

    if args.role:
        with identity.store.transaction() as conn:
            conn.execute(
                "UPDATE users SET role=?, updated_at=? WHERE id=?",
                (args.role, utc_ms(), user_id),
            )
    else:
        password = getpass("New password: ")
        if password != getpass("Confirm new password: "):
            parser.error("Passwords must match")
        try:
            password_hash = identity.hash_password(password)
        except ValueError as exc:
            parser.error(str(exc))
        now = utc_ms()
        with identity.store.transaction() as conn:
            conn.execute(
                "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
                (password_hash, now, user_id),
            )
            conn.execute(
                "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, user_id),
            )
    print("Account updated.")


if __name__ == "__main__":
    main()
