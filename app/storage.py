"""Persist uploaded documents and their extracted comments to SQLite."""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.docx_parser import Comment, extract_comments

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"


def _upload_path(user_id: int, document_id: int, filename: str) -> Path:
    """Uploaded files live under a per-user subdirectory -- filesystem-level
    isolation on top of the DB-level user_id filtering, and it means two
    users' files can never collide on disk even with the same filename."""
    safe_name = Path(filename).name  # strip any directory components
    return UPLOAD_DIR / str(user_id) / f"{document_id}_{safe_name}"


def ingest_uploaded_file(conn: sqlite3.Connection, user_id: int, filename: str, content: bytes) -> int:
    """Save an uploaded .docx, extract its comments, and store everything.

    Shared by the JSON API and the HTML upload form so extraction/storage
    behavior can't drift between the two entry points. Raises ValueError
    (with a message safe to show a user) if the file can't be read as a
    .docx -- callers turn that into a 400 response or an on-page error.
    """
    if not filename.lower().endswith(".docx"):
        raise ValueError("Only .docx files are supported.")

    document_id, saved_path = save_document(conn, user_id, filename, content)
    try:
        comments = extract_comments(saved_path)
    except (zipfile.BadZipFile, ValueError) as exc:
        raise ValueError(f"Could not read {filename}: {exc}") from exc

    save_comments(conn, document_id, comments)
    return document_id


def save_document(conn: sqlite3.Connection, user_id: int, filename: str, content: bytes) -> tuple[int, Path]:
    """Insert a documents row (owned by user_id) and write the uploaded file
    to disk.

    Returns (document_id, saved_path). The original file is kept on disk
    untouched -- comment extraction always re-reads it, nothing is derived
    from a mutated copy.
    """
    cursor = conn.execute(
        "INSERT INTO documents (user_id, filename, uploaded_at) VALUES (?, ?, ?)",
        (user_id, filename, datetime.now(timezone.utc).isoformat()),
    )
    document_id = cursor.lastrowid
    conn.commit()

    saved_path = _upload_path(user_id, document_id, filename)
    saved_path.parent.mkdir(parents=True, exist_ok=True)
    saved_path.write_bytes(content)
    return document_id, saved_path


def save_comments(conn: sqlite3.Connection, document_id: int, comments: list[Comment]) -> dict[str, int]:
    """Insert comments for a document, resolving reply-thread parent links.

    Comment.parent_id refers to another comment's docx-native id
    (unique only within the same document), not a database row id, so
    parent links are resolved in a second pass once every comment in this
    batch has a database id to point to. Returns the external_id -> db id
    mapping, which replace_document_with_revision() uses to reapply carried-
    forward decisions onto the newly-inserted rows.
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
    return external_to_db_id


def list_documents(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.id, d.filename, d.uploaded_at, COUNT(c.id) AS comment_count
        FROM documents d
        LEFT JOIN comments c ON c.document_id = d.id
        WHERE d.user_id = ?
        GROUP BY d.id
        ORDER BY d.uploaded_at DESC
        """,
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_document(conn: sqlite3.Connection, document_id: int, user_id: int) -> dict | None:
    """Returns None both when the document doesn't exist and when it
    belongs to someone else -- the two cases are indistinguishable on
    purpose, so a guessed document_id can't be used to probe whether it
    exists under another account."""
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ? AND user_id = ?", (document_id, user_id)
    ).fetchone()
    return dict(row) if row else None


def get_comment(conn: sqlite3.Connection, comment_id: int) -> dict | None:
    """Raw comment row, including document_id -- callers that receive both
    a document_id (from the URL) and a comment_id use this to confirm the
    comment actually belongs to that document before acting on it, so a
    request naming one of *your* documents can't be used to modify a
    comment that actually belongs to somebody else's."""
    row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    return dict(row) if row else None


def _delete_comments_and_derived_data(conn: sqlite3.Connection, document_id: int) -> None:
    """Deletes every comment for a document plus everything derived from
    them (conflicts, resolutions, classifications) -- but not the document
    row itself. Shared by delete_document (which also removes the document)
    and replace_document_with_revision (which keeps the document but swaps
    its comments for a freshly re-extracted set). Deletion order matters --
    foreign keys are enforced (PRAGMA foreign_keys = ON in database.py), so
    children go before parents."""
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
    conn.commit()


def delete_document(conn: sqlite3.Connection, document_id: int, user_id: int) -> bool:
    """Delete a document and everything derived from it, plus the uploaded
    file on disk. Returns False if the document didn't exist *or belongs to
    someone else* -- both look the same to the caller, True otherwise."""
    document = get_document(conn, document_id, user_id)
    if document is None:
        return False

    _delete_comments_and_derived_data(conn, document_id)
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    conn.commit()

    _upload_path(user_id, document_id, document["filename"]).unlink(missing_ok=True)

    return True


def replace_document_with_revision(
    conn: sqlite3.Connection, document_id: int, user_id: int, filename: str, content: bytes
) -> dict:
    """Re-extracts comments from a revised .docx and swaps them in, carrying
    forward each comment's classification/resolution/note wherever the new
    file has a comment from the same reviewer with identical text -- the one
    signal that survives a re-save, since Word's own comment numbering and
    this app's external ids aren't stable across saves. A comment with no
    match in the new file starts fresh (unclassified, no resolution); an old
    comment that doesn't appear in the new file at all -- e.g. a reviewer
    resolved or deleted it in Word -- is dropped.

    Keeps the same document_id, so every link, chart, and export that
    already points at this document keeps working; only the filename,
    upload timestamp, and comments change. Raises ValueError (safe to show
    a user) if the new file can't be read as a .docx, or the document
    doesn't exist.

    Returns {"carried_forward": n, "new_comments": n, "removed_comments": n}
    so the caller can tell the writer what happened to their prior work.
    """
    document = get_document(conn, document_id, user_id)
    if document is None:
        raise ValueError("Document not found.")
    if not filename.lower().endswith(".docx"):
        raise ValueError("Only .docx files are supported.")

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        try:
            new_comments = extract_comments(tmp_path)
        except (zipfile.BadZipFile, ValueError) as exc:
            raise ValueError(f"Could not read {filename}: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    old_comments = list_comments(conn, document_id)
    old_by_key: dict[tuple[str, str], list[dict]] = {}
    for old in old_comments:
        old_by_key.setdefault((old["author"] or "", old["text"]), []).append(old)

    carry_forward: dict[str, dict] = {}
    for new in new_comments:
        bucket = old_by_key.get((new.author or "", new.text))
        if bucket:
            carry_forward[new.id] = bucket.pop(0)

    carried_count = len(carry_forward)
    removed_count = sum(len(bucket) for bucket in old_by_key.values())
    new_count = len(new_comments) - carried_count

    _upload_path(user_id, document_id, document["filename"]).unlink(missing_ok=True)

    new_path = _upload_path(user_id, document_id, filename)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_bytes(content)

    conn.execute(
        "UPDATE documents SET filename = ?, uploaded_at = ? WHERE id = ?",
        (filename, datetime.now(timezone.utc).isoformat(), document_id),
    )
    conn.commit()

    _delete_comments_and_derived_data(conn, document_id)
    external_to_db_id = save_comments(conn, document_id, new_comments)

    for external_id, old in carry_forward.items():
        db_id = external_to_db_id[external_id]
        if old.get("category"):
            save_classification(conn, db_id, old["category"], old["rationale"], "carried-forward")
        if old.get("resolution_status"):
            save_resolution(conn, db_id, old["resolution_status"], old.get("resolution_note"))

    return {"carried_forward": carried_count, "new_comments": new_count, "removed_comments": removed_count}


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
               res.status AS resolution_status, res.note AS resolution_note,
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


def save_resolution(conn: sqlite3.Connection, comment_id: int, status: str | None, note: str | None = None) -> None:
    """Record (or clear, if status is None/empty) the writer's decision on a
    comment, plus an optional free-text note -- e.g. "accepted, edited
    directly in the document" or "replied in Word". This is the writer's
    own call, never set by the AI. Clearing the status clears the note too,
    since a note only makes sense attached to a decision."""
    note = (note or "").strip() or None
    if not status:
        conn.execute("DELETE FROM resolutions WHERE comment_id = ?", (comment_id,))
    else:
        conn.execute(
            """
            INSERT INTO resolutions (comment_id, status, note, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(comment_id) DO UPDATE SET
                status = excluded.status,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (comment_id, status, note, datetime.now(timezone.utc).isoformat()),
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


def save_insights(
    conn: sqlite3.Connection,
    user_id: int,
    overview: str,
    themes_json: str,
    document_count: int,
    comment_count: int,
    model: str,
) -> None:
    """Persist the latest cross-document insights for one user, replacing
    whatever was generated before for them -- like conflict detection, this
    is always a fresh full re-analysis, so there's no reason to keep old
    runs around. document_count/comment_count are recorded so the analysis
    page can tell the writer if their documents have changed since insights
    were generated."""
    conn.execute("DELETE FROM analysis_insights WHERE user_id = ?", (user_id,))
    conn.execute(
        """
        INSERT INTO analysis_insights (user_id, overview, themes_json, document_count, comment_count, model, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, overview, themes_json, document_count, comment_count, model, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_latest_insights(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM analysis_insights WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
    ).fetchone()
    return dict(row) if row else None


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


def delete_classification(conn: sqlite3.Connection, comment_id: int) -> None:
    """Clear a comment's classification, returning it to "Not classified" --
    used when a writer picks the blank option to undo an AI or manual
    category assignment."""
    conn.execute("DELETE FROM classifications WHERE comment_id = ?", (comment_id,))
    conn.commit()
