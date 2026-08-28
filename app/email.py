"""Sends transactional email via Resend's HTTP API. The only email this app
sends is an account invite -- there's no marketing or bulk sending -- so
this stays a thin wrapper around one API call rather than a general mail
library.
"""

from __future__ import annotations

import os

import httpx

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
INVITE_FROM_EMAIL = os.environ.get("INVITE_FROM_EMAIL", "Comment Insight <onboarding@resend.dev>")

_ACCENT = "#b3182f"
_MUTED = "#6b7280"


class EmailNotConfigured(RuntimeError):
    pass


def _send(to_email: str, subject: str, html: str) -> None:
    if not RESEND_API_KEY:
        raise EmailNotConfigured(
            "RESEND_API_KEY is not set -- see .env.example. Sign up at resend.com, "
            "verify a sending domain, and put the API key in your .env file."
        )
    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        json={"from": INVITE_FROM_EMAIL, "to": [to_email], "subject": subject, "html": html},
        timeout=10.0,
    )
    response.raise_for_status()


def send_invite_email(to_email: str, invite_link: str) -> None:
    html = f"""\
<div style="font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1d29;">
  <div style="border-top: 3px solid {_ACCENT}; padding-top: 1.25rem;">
    <p style="font-size: 1.15rem; font-weight: 700; margin: 0 0 0.25rem;">Comment Insight</p>
    <p style="font-size: 0.8rem; color: {_MUTED}; margin: 0 0 1.5rem;">Part of Dossentra &mdash; Medical Writing Solutions</p>
    <p style="line-height: 1.5;">You've been invited to try Comment Insight.</p>
    <p style="line-height: 1.5;">Click below to create your account and choose a password:</p>
    <p style="margin: 1.5rem 0;">
      <a href="{invite_link}" style="background: {_ACCENT}; color: #ffffff; padding: 0.65rem 1.25rem; border-radius: 6px; text-decoration: none; font-weight: 600; display: inline-block;">Create your account</a>
    </p>
    <p style="font-size: 0.8rem; color: {_MUTED};">This link works once and expires in 7 days. If you weren't expecting this, you can ignore it.</p>
  </div>
</div>
"""
    _send(to_email, "You're invited to Comment Insight", html)
