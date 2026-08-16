"""Runs classification for a document and saves the results.

Kept separate from storage.py (pure DB I/O, knows nothing about AI) and
from the classifier itself (knows nothing about SQLite) -- this is the
only place that talks to both.
"""

from __future__ import annotations

import sqlite3

from app import storage
from app.ai.base import Classifier
from app.ingestion.docx_parser import Comment


def _row_to_comment(row: dict) -> Comment:
    """The classifier takes the same Comment shape the extraction step
    produces -- rebuild one from a stored comment row. parent_id is left
    unset since classification only looks at one comment's own text."""
    return Comment(
        id=row["external_id"],
        author=row["author"],
        initials=row["initials"],
        date=row["comment_date"],
        text=row["text"],
        parent_id=None,
        anchor_text=row["anchor_text"] or "",
        paragraph_text=row["paragraph_text"] or "",
        section=row["section"],
    )


def classify_document(conn: sqlite3.Connection, document_id: int, classifier: Classifier) -> int:
    """Classify every not-yet-classified comment in a document.

    Only unclassified comments are sent to the model -- revisiting a
    document you've already classified, or clicking the button twice,
    doesn't re-spend money on comments that already have a result.
    Returns how many comments were classified in this call.
    """
    rows = storage.list_unclassified_comments(conn, document_id)
    for row in rows:
        comment = _row_to_comment(row)
        result = classifier.classify(comment)
        storage.save_classification(conn, row["id"], result.category, result.rationale, classifier.model_name)
    return len(rows)
