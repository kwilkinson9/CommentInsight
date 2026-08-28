"""Aggregates comments across every uploaded document -- shared by the
/analysis page and both of its exports (Excel, Word) so the three don't
each recompute the same numbers differently.
"""

from __future__ import annotations

import sqlite3

from app import charts, storage


def gather(conn: sqlite3.Connection, user_id: int) -> dict:
    """One pass over every document *owned by user_id*: a flat list of all
    its comments (tagged with which document they came from, conflicts
    attached, priority computed -- the same shape _document_context uses
    for a single document), a per-document summary row, and the same chart
    data the single-document page uses, just fed the combined comment
    list."""
    documents = storage.list_documents(conn, user_id)
    all_comments: list[dict] = []
    document_summaries: list[dict] = []

    for document in documents:
        comments = storage.list_comments(conn, document["id"])
        conflicts_by_comment = storage.list_conflicts_by_comment(conn, document["id"])
        status_counts = {status: 0 for status in storage.RESOLUTION_STATUSES}
        no_decision = 0

        for comment in comments:
            comment["conflicts"] = conflicts_by_comment.get(comment["id"], [])
            comment["is_priority"] = storage.is_priority(comment)
            comment["document_id"] = document["id"]
            comment["document_filename"] = document["filename"]

            status = comment.get("resolution_status")
            if status in status_counts:
                status_counts[status] += 1
            else:
                no_decision += 1

        all_comments.extend(comments)
        document_summaries.append(
            {
                "id": document["id"],
                "filename": document["filename"],
                "total": len(comments),
                "priority_count": sum(1 for c in comments if c["is_priority"]),
                "accepted": status_counts["accepted"],
                "rejected": status_counts["rejected"],
                "crm": status_counts["crm"],
                "no_decision": no_decision,
            }
        )

    return {
        "documents": documents,
        "document_summaries": document_summaries,
        "all_comments": all_comments,
        "total_documents": len(documents),
        "total_comments": len(all_comments),
        "priority_count": sum(1 for c in all_comments if c["is_priority"]),
        "chart_rows": charts.category_breakdown(all_comments),
        "resolution_chart_rows": charts.resolution_breakdown(all_comments),
        "section_hotspot_rows": charts.section_hotspots(all_comments),
    }
