from __future__ import annotations

import sqlite3
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app import storage
from app.database import get_db
from app.ingestion.docx_parser import extract_comments

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_db),
):
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported.")

    content = await file.read()
    document_id, saved_path = storage.save_document(conn, file.filename, content)

    try:
        comments = extract_comments(saved_path)
    except (zipfile.BadZipFile, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Could not read {file.filename}: {exc}"
        ) from exc

    storage.save_comments(conn, document_id, comments)
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
