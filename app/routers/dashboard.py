from __future__ import annotations

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
from app.ai.base import Classifier, ConflictDetector
from app.ai.service import classify_document, detect_conflicts_for_document
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


def _document_context(
    conn: sqlite3.Connection,
    document_id: int,
    q: str | None = None,
    author: str | None = None,
    category: str | None = None,
    sort: str = storage.DEFAULT_SORT,
    error: str | None = None,
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
        "q": q,
        "author": author,
        "category": category,
        "sort": sort,
        "current_query": current_query,
        "error": error,
    }


@router.get("/")
def index(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return templates.TemplateResponse(
        request, "index.html", {"documents": storage.list_documents(conn)}
    )


@router.get("/analysis")
def view_analysis(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return templates.TemplateResponse(request, "analysis.html", analysis.gather(conn))


@router.get("/analysis/export.docx")
def export_analysis_docx(conn: sqlite3.Connection = Depends(get_db)):
    data = analysis.gather(conn)
    content = reports.build_multi_document_report(
        data["document_summaries"],
        data["chart_rows"],
        data["resolution_chart_rows"],
        data["total_documents"],
        data["total_comments"],
        data["priority_count"],
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
    conn: sqlite3.Connection = Depends(get_db),
):
    context = _document_context(conn, document_id, q=q, author=author, category=category, sort=sort)
    return templates.TemplateResponse(request, "document.html", context)


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
    if status is not None and status not in storage.RESOLUTION_STATUSES:
        raise HTTPException(status_code=400, detail="Unrecognized resolution status.")

    storage.save_resolution(conn, comment_id, status)

    next_url = form.get("next") or f"/documents/{document_id}"
    return RedirectResponse(next_url, status_code=303)
