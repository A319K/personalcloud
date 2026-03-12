"""
files.py — FastAPI routes for file management (upload, delete, list).

Endpoints:
  POST   /files/upload    — Upload a file and generate its embedding
  DELETE /files/{file_id} — Remove a file from storage and DB
  GET    /files           — List all synced files
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from sqlalchemy.orm import Session

from db.database import get_session
from db.models import SyncedFile, FileEmbedding
from api.services.storage import StorageService, StorageError
from api.services.ocr import extract_text
from api.services.embeddings import store_chunks

router = APIRouter(prefix="/files", tags=["files"])


def _get_db():
    """FastAPI dependency that yields a database session and closes it after the request."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def _get_storage() -> StorageService:
    """FastAPI dependency that returns an initialized StorageService."""
    return StorageService()


@router.get("/", summary="List all synced files")
def list_files(db: Session = Depends(_get_db)) -> list[dict]:
    """
    Return metadata for every file currently tracked in the database.

    Returns:
        A list of file metadata dicts (id, filename, local_path, size, extension).
    """
    files = db.query(SyncedFile).order_by(SyncedFile.filename).all()
    return [
        {
            "id": f.id,
            "filename": f.filename,
            "local_path": f.local_path,
            "storage_key": f.storage_key,
            "extension": f.extension,
            "file_size": f.file_size,
            "updated_at": f.updated_at.isoformat(),
        }
        for f in files
    ]


@router.get("/{file_id}", summary="Get file detail")
def get_file_detail(
    file_id: int,
    db: Session = Depends(_get_db),
) -> dict:
    """
    Return detailed metadata and a text preview for a single synced file.

    Used by the Swift menu bar app's quick preview panel. Returns file
    metadata from synced_files plus the first 500 characters of extracted
    text from file_embeddings.

    Args:
        file_id: Database ID of the SyncedFile to retrieve.

    Returns:
        A dict matching the FileDetail Swift struct.

    Raises:
        HTTPException 404: If the file_id does not exist.
    """
    file_record = db.query(SyncedFile).filter_by(id=file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail=f"File with id={file_id} not found.")

    text_preview = ""
    if file_record.chunks:
        # Concatenate first few chunks for a richer preview
        combined = " ".join(c.extracted_text or "" for c in file_record.chunks[:3])
        text_preview = combined[:500]

    return {
        "id": str(file_record.id),
        "filename": file_record.filename,
        "local_path": file_record.local_path,
        "file_size": file_record.file_size,
        "updated_at": file_record.updated_at.isoformat(),
        "text_preview": text_preview,
    }


@router.delete("/{file_id}", summary="Delete a synced file")
def delete_file(
    file_id: int,
    db: Session = Depends(_get_db),
    storage: StorageService = Depends(_get_storage),
) -> dict:
    """
    Delete a file from storage and remove its database records.

    Args:
        file_id: Database ID of the SyncedFile to delete.

    Returns:
        Confirmation message dict.

    Raises:
        HTTPException 404: If the file_id does not exist in the database.
        HTTPException 500: If storage deletion fails.
    """
    file_record = db.query(SyncedFile).filter_by(id=file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail=f"File with id={file_id} not found.")

    # Delete from storage backend
    try:
        storage.delete_file(file_record.storage_key)
    except StorageError:
        raise HTTPException(status_code=500, detail="Failed to delete file from storage.")

    # Delete DB record (cascade removes FileEmbedding too)
    db.delete(file_record)
    db.commit()

    return {"message": f"Deleted '{file_record.filename}' successfully."}
