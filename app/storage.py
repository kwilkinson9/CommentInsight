"""Persist uploaded documents and their extracted comments to SQLite."""

from __future__ import annotations

import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.docx_parser import Comment, extract_comments

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"


def ingest_uploaded_file(conn: sqlite3.Connection, filename: str, content: bytes) -> int:
    """Save an uploaded .docx, extract its comments, and store everything.

    Shared by the JSON API and the HTML upload form so extraction/storage
    behavior can't drift between the two entry points. Raises ValueError
    (with a message safe to show a user) if the file can't be read as a
    .docx -- callers turn that into a 400 response or an on-page error.
    """
    if not filename.lower().endswith(".docx"):
        raise ValueError("Only .docx files are supported.")

    document_id, saved_path = save_document(conn, filename, content)
    try:
        comments = extract_comments(saved_path)
    except (zipfile.BadZipFile, ValueError) as exc:
        raise ValueError(f"Could not read {filename}: {exc}") from exc

    save_comments(conn, document_id, comments)
    return document_id


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


def list_comments(
    conn: sqlite3.Connection,
    document_id: int,
    q: str | None = None,
    author: str | None = None,
) -> list[dict]:
    """List comments for a document, optionally filtered by a free-text
    search (matches comment text, anchored text, or paragraph context) and/or
    an exact author match. Each row also carries parent_author, the display
    name of the comment it's replying to (or None for a top-level comment).
    """
    sql = """
        SELECT c.*, p.author AS parent_author
        FROM comments c
        LEFT JOIN comments p ON c.parent_comment_id = p.id
        WHERE c.document_id = ?
    """
    params: list = [document_id]

    if q:
        sql += " AND (c.text LIKE ? OR c.anchor_text LIKE ? OR c.paragraph_text LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like]

    if author:
        sql += " AND c.author = ?"
        params.append(author)

    sql += " ORDER BY c.id"

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def list_authors(conn: sqlite3.Connection, document_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT author FROM comments WHERE document_id = ? AND author != '' ORDER BY author",
        (document_id,),
    ).fetchall()
    return [row["author"] for row in rows]
