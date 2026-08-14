from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import storage
from app.database import get_db

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


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
            "comments": storage.list_comments(conn, document_id, q=q, author=author),
            "total_count": len(storage.list_comments(conn, document_id)),
            "authors": storage.list_authors(conn, document_id),
            "q": q,
            "author": author,
        },
    )
