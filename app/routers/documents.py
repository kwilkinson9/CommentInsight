from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app import storage
from app.database import get_db

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_db),
):
    content = await file.read()
    try:
        document_id = storage.ingest_uploaded_file(conn, file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    comments = storage.list_comments(conn, document_id)
    return {"id": document_id, "filename": file.filename, "comment_count": len(comments)}


@router.get("")
def list_documents(conn: sqlite3.Connection = Depends(get_db)):
    return storage.list_documents(conn)


@router.get("/{document_id}")
def get_document(document_id: int, conn: sqlite3.Connection = Depends(get_db)):
    document = storage.get_document(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.get("/{document_id}/comments")
def get_comments(document_id: int, conn: sqlite3.Connection = Depends(get_db)):
    document = storage.get_document(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return storage.list_comments(conn, document_id)
