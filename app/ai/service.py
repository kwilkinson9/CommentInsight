"""Runs classification for a document and saves the results.

Kept separate from storage.py (pure DB I/O, knows nothing about AI) and
from the classifier itself (knows nothing about SQLite) -- this is the
only place that talks to both.
"""

from __future__ import annotations

import json
import sqlite3

from app import analysis, deidentify, storage
from app.ai.base import AnalysisInsights, Classifier, ConflictDetector, InsightComment, InsightsGenerator
from app.deidentify import Finding
from app.ingestion.docx_parser import Comment


def _row_to_comment(row: dict, parent_id: str | None = None, redact: bool = False) -> Comment:
    """The AI interfaces take the same Comment shape the extraction step
    produces -- rebuild one from a stored comment row. When redact=True,
    the free-text fields that actually get sent to the AI (text,
    anchor_text, paragraph_text) are scrubbed via app.deidentify first --
    author/initials/date/section are left alone, since those are
    reviewer/document metadata, not prose that could contain a patient's
    details."""
    text, anchor_text, paragraph_text = row["text"], row["anchor_text"] or "", row["paragraph_text"] or ""
    if redact:
        text, _ = deidentify.redact(text)
        anchor_text, _ = deidentify.redact(anchor_text)
        paragraph_text, _ = deidentify.redact(paragraph_text)

    return Comment(
        id=row["external_id"],
        author=row["author"],
        initials=row["initials"],
        date=row["comment_date"],
        text=text,
        parent_id=parent_id,
        anchor_text=anchor_text,
        paragraph_text=paragraph_text,
        section=row["section"],
    )


def scan_document_for_identifiers(conn: sqlite3.Connection, document_id: int) -> list[Finding]:
    """Every likely-identifying detail app.deidentify can find across a
    document's comments (text, anchor_text, paragraph_text) -- used to
    decide whether to show the writer a review screen before an AI call
    that would otherwise send that text to Claude. See app/deidentify.py
    for what this can and can't catch."""
    findings: list[Finding] = []
    for row in storage.list_comments(conn, document_id):
        findings += deidentify.scan(row["text"])
        findings += deidentify.scan(row["anchor_text"])
        findings += deidentify.scan(row["paragraph_text"])
    return findings


def scan_all_documents_for_identifiers(conn: sqlite3.Connection, user_id: int) -> list[Finding]:
    """Same as scan_document_for_identifiers, but across every document a
    user has -- for the cross-document insights call, which only ever
    sends comment text (not anchor_text/paragraph_text), so that's all
    this scans."""
    data = analysis.gather(conn, user_id)
    findings: list[Finding] = []
    for comment in data["all_comments"]:
        findings += deidentify.scan(comment["text"])
    return findings


def classify_document(
    conn: sqlite3.Connection, document_id: int, classifier: Classifier, redact: bool = False
) -> int:
    """Classify every not-yet-classified comment in a document.

    Only unclassified comments are sent to the model -- revisiting a
    document you've already classified, or clicking the button twice,
    doesn't re-spend money on comments that already have a result.
    Returns how many comments were classified in this call.
    """
    rows = storage.list_unclassified_comments(conn, document_id)
    for row in rows:
        # parent_id isn't needed for single-comment classification.
        comment = _row_to_comment(row, redact=redact)
        result = classifier.classify(comment)
        storage.save_classification(conn, row["id"], result.category, result.rationale, classifier.model_name)
    return len(rows)


def detect_conflicts_for_document(
    conn: sqlite3.Connection, document_id: int, detector: ConflictDetector, redact: bool = False
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
        _row_to_comment(row, parent_id=external_id_by_db_id.get(row["parent_comment_id"]), redact=redact)
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


def generate_insights(
    conn: sqlite3.Connection, user_id: int, generator: InsightsGenerator, redact: bool = False
) -> AnalysisInsights:
    """Generate cross-document insights for one user's documents and
    persist them, replacing whatever was generated before for them. Reuses
    analysis.gather() so this sees exactly the same comment data the
    analysis page and its exports show."""
    data = analysis.gather(conn, user_id)
    comments = []
    for c in data["all_comments"]:
        text = c["text"]
        if redact:
            text, _ = deidentify.redact(text)
        comments.append(
            InsightComment(
                document_filename=c["document_filename"],
                author=c["author"],
                text=text,
                category=c.get("category"),
                resolution_status=c.get("resolution_status"),
                section=c.get("section"),
            )
        )

    result = generator.generate_insights(comments)

    storage.save_insights(
        conn,
        user_id,
        overview=result.overview,
        themes_json=json.dumps([{"title": t.title, "description": t.description} for t in result.themes]),
        document_count=data["total_documents"],
        comment_count=data["total_comments"],
        model=generator.model_name,
    )
    return result
