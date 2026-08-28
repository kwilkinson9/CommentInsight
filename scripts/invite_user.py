"""Invites a new tester to Comment Insight: creates a one-time signup link
and emails it to them, branded as Comment Insight / Dossentra. Requires
RESEND_API_KEY to be set in .env (see .env.example) -- if it isn't, the
invite is still created and this prints the link for you to send yourself.

Usage: python3 scripts/invite_user.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth
from app import email as email_module
from app.database import get_connection


def main() -> None:
    address = input("Email to invite: ").strip()
    if not address:
        print("Email can't be blank.")
        raise SystemExit(1)

    conn = get_connection()
    try:
        token = auth.create_invite(conn, address)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1)
    finally:
        conn.close()

    base_url = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    invite_link = f"{base_url}/accept-invite/{token}"

    try:
        email_module.send_invite_email(address, invite_link)
    except email_module.EmailNotConfigured as exc:
        print(f"{exc}\n\nThe invite was created, but no email was sent -- send this link yourself:\n{invite_link}\n")
        return
    except Exception as exc:
        print(f"Couldn't send the email ({exc}).\n\nThe invite was created -- send this link yourself:\n{invite_link}\n")
        return

    print(f"Invite emailed to {address}. Link (works once, expires in 7 days):\n{invite_link}\n")


if __name__ == "__main__":
    main()
