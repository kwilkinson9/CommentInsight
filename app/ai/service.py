"""Runs classification for a document and saves the results.

Kept separate from storage.py (pure DB I/O, knows nothing about AI) and
from the classifier itself (knows nothing about SQLite) -- this is the
only place that talks to both.
"""

from __future__ import annotations

import sqlite3

from app import storage
from app.ai.base import Classifier, ConflictDetector
from app.ingestion.docx_parser import Comment


def _row_to_comment(row: dict, parent_id: str | None = None) -> Comment:
    """The AI interfaces take the same Comment shape the extraction step
    produces -- rebuild one from a stored comment row."""
    return Comment(
        id=row["external_id"],
        author=row["author"],
        initials=row["initials"],
        date=row["comment_date"],
        text=row["text"],
        parent_id=parent_id,
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
        # parent_id isn't needed for single-comment classification.
        comment = _row_to_comment(row)
        result = classifier.classify(comment)
        storage.save_classification(conn, row["id"], result.category, result.rationale, classifier.model_name)
    return len(rows)


def detect_conflicts_for_document(
    conn: sqlite3.Connection, document_id: int, detector: ConflictDetector
) -> int:
    """Re-run conflict detection across every comment in a document.

    Always a full re-analysis (not incremental like classification) --
    finding conflicts means comparing every comment against every other
    one, so there's no meaningful notion of "only the new ones." Replaces
    whatever conflicts were stored from a previous run. Returns how many
    conflicting pairs were found.
    """
    rows = storage.list_comments(conn, document_id)
    db_id_by_external_id = {row["external_id"]: row["id"] for row in rows}
    external_id_by_db_id = {row["id"]: row["external_id"] for row in rows}

    comments = [
        _row_to_comment(row, parent_id=external_id_by_db_id.get(row["parent_comment_id"]))
        for row in rows
    ]

    conflict_pairs = detector.detect_conflicts(comments)

    db_pairs = [
        (db_id_by_external_id[pair.comment_id], db_id_by_external_id[pair.conflicts_with_id],
         pair.reason, detector.model_name)
        for pair in conflict_pairs
        if pair.comment_id in db_id_by_external_id and pair.conflicts_with_id in db_id_by_external_id
    ]
    storage.replace_conflicts(conn, document_id, db_pairs)
    return len(db_pairs)
