from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import storage
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


templates.env.filters["friendly_date"] = friendly_date


@router.get("/")
def index(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return templates.TemplateResponse(
        request, "index.html", {"documents": storage.list_documents(conn)}
    )


@router.post("/upload")
async def upload(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    form = await request.form()
    file: UploadFile = form["file"]
    content = await file.read()

    try:
        document_id = storage.ingest_uploaded_file(conn, file.filename, content)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"documents": storage.list_documents(conn), "error": str(exc)},
            status_code=400,
        )

    return RedirectResponse(f"/documents/{document_id}", status_code=303)


@router.get("/documents/{document_id}")
def view_document(
    document_id: int,
    request: Request,
    q: str | None = None,
    author: str | None = None,
    sort: str = storage.DEFAULT_SORT,
    conn: sqlite3.Connection = Depends(get_db),
):
    document = storage.get_document(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    return templates.TemplateResponse(
        request,
        "document.html",
        {
            "document": document,
            "comments": storage.list_comments(conn, document_id, q=q, author=author, sort=sort),
            "total_count": len(storage.list_comments(conn, document_id)),
            "authors": storage.list_authors(conn, document_id),
            "q": q,
            "author": author,
            "sort": sort,
        },
    )
