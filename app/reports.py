"""Builds a Word (.docx) report summarizing a document's comments -- meant
to be brought into a Comment Resolution Meeting (CRM).

Kept separate from storage.py (no DB access here, just dicts in -> bytes
out) so it can be tested and read on its own.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from docx import Document
from docx.shared import Pt, RGBColor

from app import storage

_MUTED = RGBColor(0x6B, 0x72, 0x80)


def _friendly_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return value
    hour_12 = dt.hour % 12 or 12
    am_pm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}, {hour_12}:{dt.minute:02d} {am_pm}"


def _muted(paragraph, text: str, size: int = 9, italic: bool = False):
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.font.color.rgb = _MUTED
    run.italic = italic
    return run


def _add_comment_block(doc: Document, comment: dict) -> None:
    heading = doc.add_paragraph()
    heading.add_run(comment["author"] or "Unknown reviewer").bold = True
    _muted(heading, f"   {_friendly_date(comment['comment_date'])}")
    if comment.get("section"):
        _muted(heading, f"   {comment['section']}", italic=True)

    meta = doc.add_paragraph()
    category = comment.get("category") or "Not classified"
    status_label = storage.RESOLUTION_LABELS.get(comment.get("resolution_status"), "No decision yet")
    _muted(meta, f"Category: {category}    |    Resolution: {status_label}")

    if comment.get("parent_author"):
        reply = doc.add_paragraph()
        _muted(reply, f"↳ reply to {comment['parent_author']}", italic=True)

    doc.add_paragraph(comment["text"])

    if comment.get("rationale"):
        rationale = doc.add_paragraph()
        _muted(rationale, comment["rationale"], italic=True)

    for conflict in comment.get("conflicts", []):
        conflict_p = doc.add_paragraph()
        conflict_p.add_run("Disagrees with another reviewer: ").bold = True
        conflict_p.add_run(f"{conflict['other_author']} — “{conflict['other_text']}”")
        reason_p = doc.add_paragraph()
        _muted(reason_p, conflict["reason"])

    if comment.get("anchor_text"):
        anchor = doc.add_paragraph()
        _muted(anchor, f"Document text: …{comment['anchor_text']}…")

    doc.add_paragraph()  # spacer between comments


def build_report(document: dict, comments: list[dict]) -> bytes:
    """Build a .docx report, grouped so comments needing team discussion
    (Decision Required, or flagged as a reviewer disagreement) come first,
    followed by a compact table of everything else."""
    doc = Document()

    doc.add_heading("Comment Resolution Report", level=0)
    doc.add_paragraph(document["filename"])
    generated = doc.add_paragraph()
    _muted(generated, f"Generated {_friendly_date(datetime.now(timezone.utc).isoformat())}")

    priority_comments = [c for c in comments if storage.is_priority(c)]
    other_comments = [c for c in comments if not storage.is_priority(c)]

    doc.add_heading("Summary", level=1)
    summary = doc.add_paragraph()
    summary.add_run(f"{len(comments)} total comment{'' if len(comments) == 1 else 's'}").bold = True
    summary.add_run(f"   ·   {len(priority_comments)} need team discussion")

    status_counts: dict[str, int] = {}
    for c in comments:
        status = c.get("resolution_status")
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
    if status_counts:
        parts = ", ".join(f"{storage.RESOLUTION_LABELS[s]}: {n}" for s, n in status_counts.items())
        doc.add_paragraph(f"Resolutions recorded so far: {parts}")

    if priority_comments:
        doc.add_heading("For Team Discussion", level=1)
        doc.add_paragraph(
            "Comments that need a specialist's sign-off, or where two reviewers were flagged as disagreeing."
        )
        for comment in priority_comments:
            _add_comment_block(doc, comment)

    if other_comments:
        doc.add_heading("Other Comments", level=1)
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        headers = ["Reviewer", "Category", "Comment", "Document Text", "Resolution"]
        for cell, text in zip(table.rows[0].cells, headers):
            cell.text = text
            cell.paragraphs[0].runs[0].bold = True

        for comment in other_comments:
            row = table.add_row().cells
            row[0].text = comment["author"] or ""
            row[1].text = comment.get("category") or "Not classified"
            row[2].text = comment["text"]
            row[3].text = comment.get("anchor_text") or ""
            row[4].text = storage.RESOLUTION_LABELS.get(comment.get("resolution_status"), "No decision yet")

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
