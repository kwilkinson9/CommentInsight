"""Persist uploaded documents and their extracted comments to SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.docx_parser import Comment

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"


def save_document(conn: sqlite3.Connection, filename: str, content: bytes) -> tuple[int, Path]:
    """Insert a documents row and write the uploaded file to disk.

    Returns (document_id, saved_path). The original file is kept on disk
    untouched -- comment extraction always re-reads it, nothing is derived
    from a mutated copy.
    """
    cursor = conn.execute(
        "INSERT INTO documents (filename, uploaded_at) VALUES (?, ?)",
        (filename, datetime.now(timezone.utc).isoformat()),
    )
    document_id = cursor.lastrowid
    conn.commit()

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name  # strip any directory components
    saved_path = UPLOAD_DIR / f"{document_id}_{safe_name}"
    saved_path.write_bytes(content)
    return document_id, saved_path


def save_comments(conn: sqlite3.Connection, document_id: int, comments: list[Comment]) -> None:
    """Insert comments for a document, resolving reply-thread parent links.

    Comment.parent_id refers to another comment's docx-native id
    (unique only within the same document), not a database row id, so
    parent links are resolved in a second pass once every comment in this
    batch has a database id to point to.
    """
    external_to_db_id: dict[str, int] = {}

    for comment in comments:
        cursor = conn.execute(
            """
            INSERT INTO comments
                (document_id, external_id, author, initials, comment_date,
                 text, anchor_text, paragraph_text, section)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id, comment.id, comment.author, comment.initials,
                comment.date, comment.text, comment.anchor_text,
                comment.paragraph_text, comment.section,
            ),
        )
        external_to_db_id[comment.id] = cursor.lastrowid

    for comment in comments:
        if comment.parent_id is not None:
            conn.execute(
                "UPDATE comments SET parent_comment_id = ? WHERE id = ?",
                (external_to_db_id.get(comment.parent_id), external_to_db_id[comment.id]),
            )

    conn.commit()


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.id, d.filename, d.uploaded_at, COUNT(c.id) AS comment_count
        FROM documents d
        LEFT JOIN comments c ON c.document_id = d.id
        GROUP BY d.id
        ORDER BY d.uploaded_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_document(conn: sqlite3.Connection, document_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return dict(row) if row else None


def list_comments(conn: sqlite3.Connection, document_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM comments WHERE document_id = ? ORDER BY id",
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]
