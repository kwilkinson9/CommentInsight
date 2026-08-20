from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app import analysis, charts, reports, storage, xlsx_reports
from app.ai.anthropic_classifier import AnthropicClassifier
from app.ai.anthropic_conflict_detector import AnthropicConflictDetector
from app.ai.anthropic_insights import AnthropicInsightsGenerator
from app.ai.base import CATEGORIES, Classifier, ConflictDetector, InsightsGenerator
from app.ai.service import classify_document, detect_conflicts_for_document, generate_insights
from app.database import get_db

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def friendly_date(value: str | None) -> str:
    """Render an ISO timestamp (e.g. from python-docx or datetime.isoformat)
    as something readable, in the server's local time zone. Falls back to
    the raw value for anything that doesn't parse -- this only ever feeds a
    template, so it should never be the reason a page fails to render."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return value
    hour_12 = dt.hour % 12 or 12
    am_pm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}, {hour_12}:{dt.minute:02d} {am_pm}"


def category_class(category: str | None) -> str:
    """CSS class slug for a category tag, e.g. "Scientific/Content" -> "cat-scientific-content"."""
    if not category:
        return ""
    return "cat-" + re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")


templates.env.filters["friendly_date"] = friendly_date
templates.env.filters["category_class"] = category_class


def get_classifier() -> Classifier:
    """FastAPI dependency, overridden in tests with a fake so the test suite
    never makes a real (paid) API call -- see tests/test_classification.py."""
    return AnthropicClassifier()


def get_conflict_detector() -> ConflictDetector:
    """Same pattern as get_classifier() -- overridden in tests."""
    return AnthropicConflictDetector()


def get_insights_generator() -> InsightsGenerator:
    """Same pattern as get_classifier() -- overridden in tests."""
    return AnthropicInsightsGenerator()


def _insights_context(conn: sqlite3.Connection) -> dict:
    """{"insights": ..., "insights_stale": ...} -- insights is None if none
    have been generated yet; insights_stale is True if the document/comment
    counts have changed since the stored insights were generated, which is
    the closest cheap proxy for "the documents changed, this may be out of
    date" without diffing actual content."""
    row = storage.get_latest_insights(conn)
    if row is None:
        return {"insights": None, "insights_stale": False}

    current = analysis.gather(conn)
    stale = (
        row["document_count"] != current["total_documents"]
        or row["comment_count"] != current["total_comments"]
    )
    return {
        "insights": {
            "overview": row["overview"],
            "themes": json.loads(row["themes_json"]),
            "created_at": row["created_at"],
            "model": row["model"],
        },
        "insights_stale": stale,
    }


def _analysis_context(conn: sqlite3.Connection, active_tab: str = "insights", error: str | None = None) -> dict:
    data = analysis.gather(conn)
    priority_comments = [c for c in data["all_comments"] if c["is_priority"]]
    return {
        **data,
        **_insights_context(conn),
        "priority_comments": priority_comments,
        "resolution_statuses": storage.RESOLUTION_STATUSES,
        "resolution_labels": storage.RESOLUTION_LABELS,
        "classification_categories": CATEGORIES,
        "active_tab": active_tab,
        "error": error,
    }


def _document_context(
    conn: sqlite3.Connection,
    document_id: int,
    q: str | None = None,
    author: str | None = None,
    category: str | None = None,
    sort: str = storage.DEFAULT_SORT,
    error: str | None = None,
    revision_summary: dict | None = None,
) -> dict:
    document = storage.get_document(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    comments = storage.list_comments(conn, document_id, q=q, author=author, category=category, sort=sort)
    conflicts_by_comment = storage.list_conflicts_by_comment(conn, document_id)
    for comment in comments:
        comment["conflicts"] = conflicts_by_comment.get(comment["id"], [])
        comment["is_priority"] = storage.is_priority(comment)

    current_query = urlencode(
        {k: v for k, v in {"q": q, "author": author, "category": category, "sort": sort}.items() if v}
    )

    all_comments = storage.list_comments(conn, document_id)

    return {
        "document": document,
        "comments": comments,
        "total_count": len(all_comments),
        "unclassified_count": len(storage.list_unclassified_comments(conn, document_id)),
        "conflict_count": sum(1 for c in comments if c["conflict_count"] > 0) if comments else 0,
        "chart_rows": charts.category_breakdown(all_comments),
        "resolution_chart_rows": charts.resolution_breakdown(all_comments),
        "authors": storage.list_authors(conn, document_id),
        "categories": storage.list_categories(conn, document_id),
        "resolution_statuses": storage.RESOLUTION_STATUSES,
        "resolution_labels": storage.RESOLUTION_LABELS,
        "classification_categories": CATEGORIES,
        "q": q,
        "author": author,
        "category": category,
        "sort": sort,
        "current_query": current_query,
        "error": error,
        "revision_summary": revision_summary,
    }


@router.get("/")
def index(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return templates.TemplateResponse(
        request, "index.html", {"documents": storage.list_documents(conn)}
    )


@router.get("/analysis")
def view_analysis(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return templates.TemplateResponse(request, "analysis.html", _analysis_context(conn, active_tab="insights"))


@router.get("/analysis/charts")
def view_analysis_charts(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return templates.TemplateResponse(request, "analysis.html", _analysis_context(conn, active_tab="charts"))


@router.post("/analysis/insights")
def create_analysis_insights(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    generator: InsightsGenerator = Depends(get_insights_generator),
):
    try:
        generate_insights(conn, generator)
    except Exception as exc:
        context = _analysis_context(conn, active_tab="insights", error=f"Insight generation failed: {exc}")
        return templates.TemplateResponse(request, "analysis.html", context, status_code=502)

    return RedirectResponse("/analysis", status_code=303)


@router.get("/analysis/export.docx")
def export_analysis_docx(conn: sqlite3.Connection = Depends(get_db)):
    data = analysis.gather(conn)
    insights = _insights_context(conn)["insights"]
    content = reports.build_multi_document_report(
        data["document_summaries"],
        data["chart_rows"],
        data["resolution_chart_rows"],
        data["total_documents"],
        data["total_comments"],
        data["priority_count"],
        insights=insights,
        section_hotspot_rows=data["section_hotspot_rows"],
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="comment_insight_analysis_report.docx"'},
    )


@router.get("/analysis/export.xlsx")
def export_analysis_xlsx(conn: sqlite3.Connection = Depends(get_db)):
    data = analysis.gather(conn)
    content = xlsx_reports.build_workbook(
        data["document_summaries"],
        data["chart_rows"],
        data["resolution_chart_rows"],
        data["all_comments"],
        section_hotspot_rows=data["section_hotspot_rows"],
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="comment_insight_analysis.xlsx"'},
    )


@router.post("/upload")
async def upload(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    form = await request.form()
    files: list[UploadFile] = form.getlist("file")
    if not files:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"documents": storage.list_documents(conn), "error": "Please choose at least one file."},
            status_code=400,
        )

    document_ids = []
    errors = []
    for file in files:
        content = await file.read()
        try:
            document_ids.append(storage.ingest_uploaded_file(conn, file.filename, content))
        except ValueError as exc:
            errors.append(f"{file.filename}: {exc}")

    if errors:
        error_message = "Some files couldn't be uploaded: " + "; ".join(errors)
        return templates.TemplateResponse(
            request,
            "index.html",
            {"documents": storage.list_documents(conn), "error": error_message},
            status_code=400,
        )

    if len(document_ids) == 1:
        return RedirectResponse(f"/documents/{document_ids[0]}", status_code=303)

    return RedirectResponse("/", status_code=303)


@router.post("/documents/{document_id}/delete")
def delete_document(document_id: int, conn: sqlite3.Connection = Depends(get_db)):
    if not storage.delete_document(conn, document_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    return RedirectResponse("/", status_code=303)


@router.get("/documents/{document_id}")
def view_document(
    document_id: int,
    request: Request,
    q: str | None = None,
    author: str | None = None,
    category: str | None = None,
    sort: str = storage.DEFAULT_SORT,
    revised_carried: int | None = None,
    revised_new: int | None = None,
    revised_removed: int | None = None,
    conn: sqlite3.Connection = Depends(get_db),
):
    revision_summary = None
    if revised_carried is not None:
        revision_summary = {"carried_forward": revised_carried, "new_comments": revised_new, "removed_comments": revised_removed}
    context = _document_context(conn, document_id, q=q, author=author, category=category, sort=sort, revision_summary=revision_summary)
    return templates.TemplateResponse(request, "document.html", context)


@router.post("/documents/{document_id}/revise")
async def revise_document(
    document_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Swaps in a revised .docx for an existing document, carrying forward
    classification/resolution decisions for comments that match one from
    before -- see storage.replace_document_with_revision()."""
    if storage.get_document(conn, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    form = await request.form()
    file: UploadFile | None = form.get("file")
    if file is None or not file.filename:
        return templates.TemplateResponse(
            request,
            "document.html",
            _document_context(conn, document_id, error="Please choose a .docx file to upload as the revision."),
            status_code=400,
        )

    content = await file.read()
    try:
        summary = storage.replace_document_with_revision(conn, document_id, file.filename, content)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "document.html",
            _document_context(conn, document_id, error=str(exc)),
            status_code=400,
        )

    redirect_url = (
        f"/documents/{document_id}?revised_carried={summary['carried_forward']}"
        f"&revised_new={summary['new_comments']}&revised_removed={summary['removed_comments']}"
    )
    return RedirectResponse(redirect_url, status_code=303)


@router.get("/documents/{document_id}/export")
def export_report(document_id: int, conn: sqlite3.Connection = Depends(get_db)):
    document = storage.get_document(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    comments = storage.list_comments(conn, document_id)
    conflicts_by_comment = storage.list_conflicts_by_comment(conn, document_id)
    for comment in comments:
        comment["conflicts"] = conflicts_by_comment.get(comment["id"], [])

    content = reports.build_report(document, comments)
    filename = f"{Path(document['filename']).stem}_comment_report.docx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/documents/{document_id}/classify")
async def classify(
    document_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    classifier: Classifier = Depends(get_classifier),
):
    if storage.get_document(conn, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    form = await request.form()
    next_url = form.get("next") or f"/documents/{document_id}"

    try:
        classify_document(conn, document_id, classifier)
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "document.html",
            _document_context(conn, document_id, error=f"Classification failed: {exc}"),
            status_code=502,
        )

    return RedirectResponse(next_url, status_code=303)


@router.post("/documents/{document_id}/detect-conflicts")
async def detect_conflicts(
    document_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    detector: ConflictDetector = Depends(get_conflict_detector),
):
    if storage.get_document(conn, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    form = await request.form()
    next_url = form.get("next") or f"/documents/{document_id}"

    try:
        detect_conflicts_for_document(conn, document_id, detector)
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "document.html",
            _document_context(conn, document_id, error=f"Conflict check failed: {exc}"),
            status_code=502,
        )

    return RedirectResponse(next_url, status_code=303)


@router.post("/documents/{document_id}/comments/{comment_id}/resolution")
async def set_resolution(
    document_id: int,
    comment_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    if storage.get_document(conn, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    form = await request.form()
    status = (form.get("status") or "").strip() or None
    note = form.get("note")
    if status is not None and status not in storage.RESOLUTION_STATUSES:
        raise HTTPException(status_code=400, detail="Unrecognized resolution status.")

    storage.save_resolution(conn, comment_id, status, note)

    next_url = form.get("next") or f"/documents/{document_id}"
    return RedirectResponse(next_url, status_code=303)


@router.post("/documents/{document_id}/comments/{comment_id}/category")
async def set_category(
    document_id: int,
    comment_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Lets the writer set or correct a comment's category by hand -- e.g.
    fixing something the AI got wrong, or classifying a comment without
    running AI classification at all. Recorded the same way an AI
    classification is (the classifications table), just with model="manual"
    so it's clear in exports that a person, not the AI, made the call."""
    if storage.get_document(conn, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    form = await request.form()
    category = (form.get("category") or "").strip() or None
    if category is not None and category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Unrecognized category.")

    if category is None:
        storage.delete_classification(conn, comment_id)
    else:
        storage.save_classification(conn, comment_id, category, "Set manually by the writer.", "manual")

    next_url = form.get("next") or f"/documents/{document_id}"
    return RedirectResponse(next_url, status_code=303)
