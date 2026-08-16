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


def delete_document(conn: sqlite3.Connection, document_id: int) -> bool:
    """Delete a document and everything derived from it (conflicts,
    resolutions, classifications, comments) plus the uploaded file on disk.
    Returns False if the document didn't exist, True otherwise. Deletion
    order matters -- foreign keys are enforced (PRAGMA foreign_keys = ON in
    database.py), so children go before parents."""
    document = get_document(conn, document_id)
    if document is None:
        return False

    conn.execute("DELETE FROM conflicts WHERE document_id = ?", (document_id,))
    conn.execute(
        "DELETE FROM resolutions WHERE comment_id IN (SELECT id FROM comments WHERE document_id = ?)",
        (document_id,),
    )
    conn.execute(
        "DELETE FROM classifications WHERE comment_id IN (SELECT id FROM comments WHERE document_id = ?)",
        (document_id,),
    )
    conn.execute("DELETE FROM comments WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    conn.commit()

    safe_name = Path(document["filename"]).name
    saved_path = UPLOAD_DIR / f"{document_id}_{safe_name}"
    saved_path.unlink(missing_ok=True)

    return True


SORT_OPTIONS = {
    "priority": "CASE WHEN category = 'Decision Required' OR conflict_count > 0 THEN 0 ELSE 1 END, c.id",
    "document": "c.id",
    "date": "c.comment_date IS NULL, c.comment_date, c.id",
    "reviewer": "c.author COLLATE NOCASE, c.id",
}
# "document" (stable, unaffected by classification results) rather than
# "priority" -- with priority as the default, running classification would
# make newly-flagged Decision Required comments jump to the top of the list
# the writer was already reading through. Priority is still one click away
# in the sort dropdown for whoever wants that view.
DEFAULT_SORT = "document"

def is_priority(comment: dict) -> bool:
    """A comment needs the writer's attention above the rest of the pile
    when it either needs someone else's sign-off (Decision Required) or
    two reviewers were flagged as disagreeing about it."""
    return comment.get("category") == "Decision Required" or (comment.get("conflict_count") or 0) > 0


RESOLUTION_STATUSES = ["accepted", "rejected", "crm"]
RESOLUTION_LABELS = {
    "accepted": "Accepted",
    "rejected": "Rejected",
    "crm": "CRM (needs meeting)",
}


def list_comments(
    conn: sqlite3.Connection,
    document_id: int,
    q: str | None = None,
    author: str | None = None,
    category: str | None = None,
    sort: str = DEFAULT_SORT,
) -> list[dict]:
    """List comments for a document, optionally filtered by a free-text
    search (matches comment text, anchored text, or paragraph context), an
    exact author match, and/or an exact classification category. Each row
    also carries parent_author (the name of the comment it's replying to, or
    None), category/rationale (if classified), resolution_status (if the
    writer has recorded one), and conflict_count (how many other comments
    it's been flagged as disagreeing with).

    `sort` picks the ordering: "priority" (comments needing team input or
    flagged as conflicting first, the default), "document" (as it appears
    in the file), "date", or "reviewer". An unrecognized value falls back
    to the default rather than erroring, since it only ever comes from a
    URL query string that a user could hand-edit.
    """
    sql = """
        SELECT c.*, p.author AS parent_author, cl.category AS category, cl.rationale AS rationale,
               res.status AS resolution_status,
               (SELECT COUNT(*) FROM conflicts cf
                WHERE cf.comment_id = c.id OR cf.conflicts_with_comment_id = c.id) AS conflict_count
        FROM comments c
        LEFT JOIN comments p ON c.parent_comment_id = p.id
        LEFT JOIN classifications cl ON cl.comment_id = c.id
        LEFT JOIN resolutions res ON res.comment_id = c.id
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

    if category:
        sql += " AND cl.category = ?"
        params.append(category)

    sql += " ORDER BY " + SORT_OPTIONS.get(sort, SORT_OPTIONS[DEFAULT_SORT])

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def save_resolution(conn: sqlite3.Connection, comment_id: int, status: str | None) -> None:
    """Record (or clear, if status is None/empty) the writer's decision on a
    comment. This is the writer's own call, never set by the AI."""
    if not status:
        conn.execute("DELETE FROM resolutions WHERE comment_id = ?", (comment_id,))
    else:
        conn.execute(
            """
            INSERT INTO resolutions (comment_id, status, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(comment_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (comment_id, status, datetime.now(timezone.utc).isoformat()),
        )
    conn.commit()


def replace_conflicts(
    conn: sqlite3.Connection, document_id: int, pairs: list[tuple[int, int, str, str]]
) -> None:
    """Replace this document's conflict list wholesale. Conflict detection
    always looks at every comment together, so (unlike classification) a
    re-run is a fresh full analysis, not an incremental one -- the old
    results are cleared first. `pairs` is (comment_id, conflicts_with_comment_id,
    reason, model)."""
    conn.execute(
        "DELETE FROM conflicts WHERE document_id = ?",
        (document_id,),
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO conflicts (document_id, comment_id, conflicts_with_comment_id, reason, model, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(document_id, a, b, reason, model, now) for a, b, reason, model in pairs],
    )
    conn.commit()


def list_conflicts_by_comment(conn: sqlite3.Connection, document_id: int) -> dict[int, list[dict]]:
    """Conflict details grouped by comment_id, from both sides of each pair
    (a comment shows up here whether it was stored as the first or second
    half of the pair) -- {comment_id: [{other_author, other_text, reason}]}."""
    rows = conn.execute(
        """
        SELECT cf.comment_id, cf.reason, other.author AS other_author, other.text AS other_text
        FROM conflicts cf
        JOIN comments other ON other.id = cf.conflicts_with_comment_id
        WHERE cf.document_id = ?
        UNION ALL
        SELECT cf.conflicts_with_comment_id AS comment_id, cf.reason, other.author AS other_author, other.text AS other_text
        FROM conflicts cf
        JOIN comments other ON other.id = cf.comment_id
        WHERE cf.document_id = ?
        """,
        (document_id, document_id),
    ).fetchall()

    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["comment_id"], []).append(
            {"other_author": row["other_author"], "other_text": row["other_text"], "reason": row["reason"]}
        )
    return grouped


def list_authors(conn: sqlite3.Connection, document_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT author FROM comments WHERE document_id = ? AND author != '' ORDER BY author",
        (document_id,),
    ).fetchall()
    return [row["author"] for row in rows]


def list_categories(conn: sqlite3.Connection, document_id: int) -> list[str]:
    """Categories actually assigned so far in this document (not the full
    fixed list) -- if nothing's been classified yet, this is empty."""
    rows = conn.execute(
        """
        SELECT DISTINCT cl.category
        FROM classifications cl
        JOIN comments c ON c.id = cl.comment_id
        WHERE c.document_id = ?
        ORDER BY cl.category
        """,
        (document_id,),
    ).fetchall()
    return [row["category"] for row in rows]


def list_unclassified_comments(conn: sqlite3.Connection, document_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.* FROM comments c
        LEFT JOIN classifications cl ON cl.comment_id = c.id
        WHERE c.document_id = ? AND cl.id IS NULL
        ORDER BY c.id
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def save_classification(
    conn: sqlite3.Connection, comment_id: int, category: str, rationale: str, model: str
) -> None:
    """Insert or replace this comment's classification. Re-running
    classification on an already-classified comment overwrites the old
    result rather than keeping history -- fine for now since there's only
    ever one active classification per comment."""
    conn.execute(
        """
        INSERT INTO classifications (comment_id, category, rationale, model, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(comment_id) DO UPDATE SET
            category = excluded.category,
            rationale = excluded.rationale,
            model = excluded.model,
            created_at = excluded.created_at
        """,
        (comment_id, category, rationale, model, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
