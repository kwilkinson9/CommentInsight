"""Generates a one-time password reset link for a tester who's forgotten
their password. Admin runs this, then sends the printed link to them
through whatever channel you already use to send credentials -- it's not
emailed automatically, so it only reaches whoever you paste it to.

The link works once and expires after an hour.

Usage: python3 scripts/reset_password.py
"""

from __future__ import annotations

import os
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

    conn = get_connection()
    try:
        token = auth.create_reset_token(conn, email)
    finally:
        conn.close()

    if token is None:
        print(f"No account found for {email}.")
        raise SystemExit(1)

    base_url = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    print(f"\nReset link (works once, expires in 1 hour):\n{base_url}/reset-password/{token}\n")


if __name__ == "__main__":
    main()
