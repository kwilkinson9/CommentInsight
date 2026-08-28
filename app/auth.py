"""User accounts and session authentication.

This app started as a single-user local tool with no login at all. Once it
runs on a shared server that more than one person reaches over the network,
every document has to belong to exactly one account, and every route has to
prove who's asking before it touches the database -- that's what this
module and the per-user filtering in storage.py exist to guarantee.

Accounts are created by an admin (see scripts/create_user.py), not by open
self-signup -- this is meant for a known, small group of testers, not the
public internet.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request

from app.database import get_db

_LOGIN_ATTEMPT_LIMIT = 5
_LOGIN_ATTEMPT_WINDOW_SECONDS = 15 * 60

# How long an admin-generated reset link stays usable. Short enough that a
# link sitting in an old chat/email isn't a standing risk, long enough that
# a tester who's sent one has a reasonable window to act on it.
_RESET_TOKEN_TTL_SECONDS = 60 * 60

# Invites get a longer window than resets -- they're not a "someone's locked
# out right now" recovery link, and a tester might not get to onboarding
# the same day it's sent.
_INVITE_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60

# bcrypt's cost factor is deliberately expensive (that's the point -- it
# slows down offline brute-forcing of a stolen hash). 12 is a solid default
# for real accounts; the test suite creates throwaway users constantly and
# overrides this to bcrypt's minimum (4) via tests/__init__.py so the suite
# doesn't spend most of its time hashing test passwords nobody needs to
# protect.
_BCRYPT_ROUNDS = int(os.environ.get("BCRYPT_ROUNDS", "12"))


class _LoginRateLimiter:
    """Blocks repeated failed logins against the same email -- a simple
    in-memory counter, not a distributed one. That's the right tradeoff for
    a small pilot behind a single server process; it resets on restart and
    wouldn't coordinate across multiple worker processes, which is fine
    until this needs to scale past that."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_blocked(self, email: str) -> bool:
        with self._lock:
            attempts = self._recent_attempts(email)
            return len(attempts) >= _LOGIN_ATTEMPT_LIMIT

    def record_failure(self, email: str) -> None:
        with self._lock:
            attempts = self._recent_attempts(email)
            attempts.append(time.monotonic())
            self._failures[email] = attempts

    def record_success(self, email: str) -> None:
        with self._lock:
            self._failures.pop(email, None)

    def _recent_attempts(self, email: str) -> list[float]:
        cutoff = time.monotonic() - _LOGIN_ATTEMPT_WINDOW_SECONDS
        attempts = [t for t in self._failures.get(email, []) if t >= cutoff]
        self._failures[email] = attempts
        return attempts


_rate_limiter = _LoginRateLimiter()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash -- treat as a failed login rather than a crash.
        return False


def create_user(conn: sqlite3.Connection, email: str, password: str) -> int:
    """Raises ValueError (safe to show whoever's creating the account) if
    the email is already registered."""
    email = email.strip().lower()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing is not None:
        raise ValueError(f"An account already exists for {email}.")

    cursor = conn.execute(
        "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
        (email, hash_password(password), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return cursor.lastrowid


def get_user_by_email(conn: sqlite3.Connection, email: str) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    return dict(row) if row else None


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def authenticate(conn: sqlite3.Connection, email: str, password: str) -> dict | None:
    """Returns the user row on success, None on a wrong email/password or
    while rate-limited. Deliberately gives the same "incorrect email or
    password" outcome for an unknown email as for a wrong password, so a
    login attempt can't be used to discover which emails have accounts."""
    email = email.strip().lower()
    if _rate_limiter.is_blocked(email):
        return None

    user = get_user_by_email(conn, email)
    if user is None or not verify_password(password, user["password_hash"]):
        _rate_limiter.record_failure(email)
        return None

    _rate_limiter.record_success(email)
    return user


def _hash_token(raw_token: str) -> str:
    # These tokens are 256 bits of randomness, not user-chosen secrets like
    # passwords -- there's nothing for an offline attacker to guess, so a
    # plain fast hash (unlike bcrypt) is enough to keep a stolen database
    # from directly handing over a usable link.
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_reset_token(conn: sqlite3.Connection, email: str) -> str | None:
    """Admin-facing: generates a one-time password reset token for the
    given email. Returns the raw token (only ever available here -- only
    its hash is stored) or None if no account matches that email."""
    user = get_user_by_email(conn, email)
    if user is None:
        return None

    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=_RESET_TOKEN_TTL_SECONDS)
    conn.execute(
        "INSERT INTO password_reset_tokens (user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (user["id"], _hash_token(raw_token), now.isoformat(), expires_at.isoformat()),
    )
    conn.commit()
    return raw_token


def get_valid_reset_token(conn: sqlite3.Connection, raw_token: str) -> dict | None:
    """Returns the token row if raw_token is real, unused, and unexpired --
    None otherwise. Used both to decide whether to show the reset form and,
    again, to guard against the token expiring or being used a second time
    between showing that form and submitting it."""
    row = conn.execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash = ?", (_hash_token(raw_token),)
    ).fetchone()
    if row is None:
        return None
    row = dict(row)
    if row["used_at"] is not None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return None
    return row


def reset_password(conn: sqlite3.Connection, raw_token: str, new_password: str) -> bool:
    """Consumes a reset token and sets the new password. Returns False (and
    changes nothing) if the token is missing, expired, or already used."""
    token_row = get_valid_reset_token(conn, raw_token)
    if token_row is None:
        return False

    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(new_password), token_row["user_id"]),
    )
    conn.execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), token_row["id"]),
    )
    conn.commit()
    return True


def create_invite(conn: sqlite3.Connection, email: str) -> str:
    """Admin-facing: generates a one-time signup token for the given email.
    Raises ValueError (safe to show whoever's inviting) if an account
    already exists for that email -- catches the "meant to invite someone
    new, typo'd an existing tester's address" mistake immediately instead
    of producing a link that fails later."""
    email = email.strip().lower()
    if get_user_by_email(conn, email) is not None:
        raise ValueError(f"An account already exists for {email}.")

    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=_INVITE_TOKEN_TTL_SECONDS)
    conn.execute(
        "INSERT INTO invites (email, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (email, _hash_token(raw_token), now.isoformat(), expires_at.isoformat()),
    )
    conn.commit()
    return raw_token


def get_valid_invite(conn: sqlite3.Connection, raw_token: str) -> dict | None:
    """Returns the invite row if raw_token is real, unaccepted, and
    unexpired -- None otherwise."""
    row = conn.execute("SELECT * FROM invites WHERE token_hash = ?", (_hash_token(raw_token),)).fetchone()
    if row is None:
        return None
    row = dict(row)
    if row["accepted_at"] is not None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return None
    return row


def accept_invite(conn: sqlite3.Connection, raw_token: str, password: str) -> int | None:
    """Consumes an invite token, creating the account it names. Returns the
    new user's id, or None if the token is missing/expired/already used --
    or if the invited email was somehow claimed in the meantime, in which
    case the invite is still spent so it can't be retried."""
    invite = get_valid_invite(conn, raw_token)
    if invite is None:
        return None

    now = datetime.now(timezone.utc).isoformat()
    try:
        user_id = create_user(conn, invite["email"], password)
    except ValueError:
        conn.execute("UPDATE invites SET accepted_at = ? WHERE id = ?", (now, invite["id"]))
        conn.commit()
        return None

    conn.execute("UPDATE invites SET accepted_at = ? WHERE id = ?", (now, invite["id"]))
    conn.commit()
    return user_id


def require_user(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """FastAPI dependency: the logged-in user, or a redirect to /login.

    Raising an HTTPException with a Location header works as a real
    redirect here -- browsers act on the 3xx status and Location header
    before ever looking at the body, so the JSON error body FastAPI
    attaches by default is never seen. Every route that touches a document
    (HTML pages and the JSON API alike) depends on this.
    """
    user_id = request.session.get("user_id")
    user = get_user_by_id(conn, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user
