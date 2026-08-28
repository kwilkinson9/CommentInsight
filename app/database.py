"""SQLite connection and schema for documents and their extracted comments."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "comment_insight.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    external_id TEXT NOT NULL,
    author TEXT,
    initials TEXT,
    comment_date TEXT,
    text TEXT NOT NULL,
    anchor_text TEXT,
    paragraph_text TEXT,
    section TEXT,
    parent_comment_id INTEGER REFERENCES comments(id),
    UNIQUE(document_id, external_id)
);

CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id INTEGER NOT NULL REFERENCES comments(id),
    category TEXT NOT NULL,
    rationale TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(comment_id)
);

CREATE TABLE IF NOT EXISTS resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id INTEGER NOT NULL REFERENCES comments(id),
    status TEXT NOT NULL,
    note TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(comment_id)
);

CREATE TABLE IF NOT EXISTS conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    comment_id INTEGER NOT NULL REFERENCES comments(id),
    conflicts_with_comment_id INTEGER NOT NULL REFERENCES comments(id),
    reason TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    overview TEXT NOT NULL,
    themes_json TEXT NOT NULL,
    document_count INTEGER NOT NULL,
    comment_count INTEGER NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    accepted_at TEXT
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Adds columns introduced after a table already shipped -- CREATE TABLE
    IF NOT EXISTS in SCHEMA only helps installs starting fresh, so anyone
    with an existing database.db needs these ALTER TABLEs to pick up new
    columns without losing their data."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(resolutions)").fetchall()}
    if "note" not in columns:
        conn.execute("ALTER TABLE resolutions ADD COLUMN note TEXT")
        conn.commit()

    _migrate_to_multi_user(conn)


def _migrate_to_multi_user(conn: sqlite3.Connection) -> None:
    """A database created before accounts existed has documents/insights
    with no owner. Rather than silently losing them, this folds every
    ownerless document into one freshly-created account and prints its
    (randomly generated) credentials once -- the only way to reach that
    data again, so this only ever needs to run the first time a pre-auth
    database is opened after upgrading."""
    doc_columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "user_id" in doc_columns:
        return

    conn.execute("ALTER TABLE documents ADD COLUMN user_id INTEGER REFERENCES users(id)")
    orphaned = conn.execute("SELECT COUNT(*) AS n FROM documents WHERE user_id IS NULL").fetchone()["n"]

    if orphaned:
        import secrets

        from app import auth

        email = "local@commentinsight.local"
        password = secrets.token_urlsafe(12)
        user_id = auth.create_user(conn, email, password)
        conn.execute("UPDATE documents SET user_id = ? WHERE user_id IS NULL", (user_id,))
        print(
            f"\n[Comment Insight] This database predates user accounts. Your "
            f"{orphaned} existing document(s) have been moved into a new account:\n"
            f"  email:    {email}\n"
            f"  password: {password}\n"
            f"Log in with these -- you can change the password afterwards. This "
            f"message only appears once.\n"
        )

    # analysis_insights is a disposable cache (regenerated on demand), so
    # rather than guessing which account it belonged to, just clear it.
    insights_columns = {row["name"] for row in conn.execute("PRAGMA table_info(analysis_insights)").fetchall()}
    if "user_id" not in insights_columns:
        conn.execute("DELETE FROM analysis_insights")
        conn.execute("ALTER TABLE analysis_insights ADD COLUMN user_id INTEGER REFERENCES users(id)")

    conn.commit()


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def get_db():
    """FastAPI dependency: yields a connection, closes it after the request.

    Tests override this dependency to point at a temporary database instead
    of the real one -- see tests/test_documents_api.py.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
