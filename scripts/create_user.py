"""Creates a login for Comment Insight. Accounts are admin-created, not
self-signup -- run this once per tester, then send them their email and
password through some channel other than this terminal's scrollback
(they should treat the password as theirs alone from that point on).

Usage: python3 scripts/create_user.py
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth
from app.database import get_connection


def main() -> None:
    email = input("Email: ").strip()
    if not email:
        print("Email can't be blank.")
        raise SystemExit(1)

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords didn't match.")
        raise SystemExit(1)
    if len(password) < 8:
        print("Use at least 8 characters.")
        raise SystemExit(1)

    conn = get_connection()
    try:
        user_id = auth.create_user(conn, email, password)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1)
    finally:
        conn.close()

    print(f"Created account #{user_id} for {email}.")


if __name__ == "__main__":
    main()
