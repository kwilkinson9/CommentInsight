from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app import auth, storage
from app.database import get_db

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_db),
    user: dict = Depends(auth.require_user),
):
    content = await file.read()
    try:
        document_id = storage.ingest_uploaded_file(conn, user["id"], file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    comments = storage.list_comments(conn, document_id)
    return {"id": document_id, "filename": file.filename, "comment_count": len(comments)}


@router.get("")
def list_documents(conn: sqlite3.Connection = Depends(get_db), user: dict = Depends(auth.require_user)):
    return storage.list_documents(conn, user["id"])


@router.get("/{document_id}")
def get_document(
    document_id: int, conn: sqlite3.Connection = Depends(get_db), user: dict = Depends(auth.require_user)
):
    document = storage.get_document(conn, document_id, user["id"])
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.get("/{document_id}/comments")
def get_comments(
    document_id: int, conn: sqlite3.Connection = Depends(get_db), user: dict = Depends(auth.require_user)
):
    document = storage.get_document(conn, document_id, user["id"])
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return storage.list_comments(conn, document_id)
