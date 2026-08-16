"""SQLite connection and schema for documents and their extracted comments."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "comment_insight.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
"""


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
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
