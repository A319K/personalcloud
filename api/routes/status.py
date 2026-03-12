"""
status.py — FastAPI routes for sync status, watcher control, and health.

Endpoints:
  GET  /status          — Returns SyncStatus JSON for the Swift menu bar app
  POST /watcher/start   — Starts the background file watcher thread
  POST /watcher/stop    — Stops the background file watcher thread
"""

import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text as sql_text

from db.database import get_session
from db.models import SyncedFile, FileEmbedding
from config.settings import settings

router = APIRouter(tags=["status"])

# ---------------------------------------------------------------------------
# Watcher thread state — module-level singleton
# ---------------------------------------------------------------------------

_watcher_thread: threading.Thread | None = None
_watcher_observer = None  # watchdog Observer instance
_watcher_lock = threading.Lock()


def _get_db():
    """FastAPI dependency that yields a database session and closes it after the request."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Sync helper used by the background watcher thread
# ---------------------------------------------------------------------------

def _sync_file_background(file_path: Path) -> None:
    """
    Sync a single file to storage and generate its embedding.

    Called from the background watcher thread when a file is created or modified.
    Opens its own DB session since it runs off the main thread.

    Args:
        file_path: Absolute path to the file to sync.
    """
    from db.database import get_session
    from db.models import SyncedFile
    from api.services.storage import StorageService, StorageError
    from api.services.ocr import extract_text
    from api.services.embeddings import generate_embedding, store_embedding

    watch_folder = settings.watch_folder_path
    try:
        storage_key = str(file_path.relative_to(watch_folder))
    except ValueError:
        storage_key = file_path.name

    try:
        stat = file_path.stat()
        current_mtime = int(stat.st_mtime)
        current_size = stat.st_size
    except OSError:
        return  # file was removed between event and processing

    session = get_session()
    try:
        existing = session.query(SyncedFile).filter_by(local_path=str(file_path)).first()
        if existing and existing.last_modified_ts == current_mtime:
            return  # unchanged

        storage = StorageService()
        storage.upload_file(file_path, storage_key)
        text = extract_text(file_path)
        embedding_vector = generate_embedding(text)

        if existing:
            existing.storage_key = storage_key
            existing.file_size = current_size
            existing.last_modified_ts = current_mtime
            existing.updated_at = datetime.utcnow()
            session.commit()
            file_id = existing.id
        else:
            new_file = SyncedFile(
                local_path=str(file_path),
                storage_key=storage_key,
                filename=file_path.name,
                extension=file_path.suffix.lower(),
                file_size=current_size,
                last_modified_ts=current_mtime,
            )
            session.add(new_file)
            session.commit()
            file_id = new_file.id

        store_embedding(session, file_id, text, embedding_vector)
    except Exception:
        pass  # watcher thread — swallow errors silently
    finally:
        session.close()


def _delete_file_background(file_path: Path) -> None:
    """
    Remove a deleted file's DB record and storage object.

    Called from the background watcher thread when a file is deleted.

    Args:
        file_path: The local path of the deleted file.
    """
    from db.database import get_session
    from db.models import SyncedFile
    from api.services.storage import StorageService, StorageError

    session = get_session()
    try:
        record = session.query(SyncedFile).filter_by(local_path=str(file_path)).first()
        if not record:
            return
        try:
            StorageService().delete_file(record.storage_key)
        except StorageError:
            pass
        session.delete(record)
        session.commit()
    except Exception:
        pass
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

@router.get("/status", summary="Get sync status")
def get_status(db: Session = Depends(_get_db)) -> dict:
    """
    Return current sync statistics for the personalcloud menu bar app.

    Queries the database for total file count, storage usage, and most
    recent sync timestamp. Also reports whether the background watcher
    thread is currently active.

    Returns:
        A dict matching the SyncStatus Swift struct:
          last_synced, total_files, storage_used_mb, watcher_active.
    """
    try:
        total_files = db.query(func.count(SyncedFile.id)).scalar() or 0
        total_bytes = db.query(func.sum(SyncedFile.file_size)).scalar() or 0
        last_synced_row = db.query(func.max(SyncedFile.updated_at)).scalar()
    except Exception:
        total_files = 0
        total_bytes = 0
        last_synced_row = None

    storage_used_mb = round(float(total_bytes) / (1024 * 1024), 2)
    last_synced = last_synced_row.isoformat() if last_synced_row else None

    with _watcher_lock:
        active = _watcher_thread is not None and _watcher_thread.is_alive()

    return {
        "last_synced": last_synced,
        "total_files": total_files,
        "storage_used_mb": storage_used_mb,
        "watcher_active": active,
    }


# ---------------------------------------------------------------------------
# Watcher control endpoints
# ---------------------------------------------------------------------------

@router.post("/watcher/start", summary="Start background file watcher")
def start_watcher() -> dict:
    """
    Start the watchdog file system watcher in a background daemon thread.

    If the watcher is already running, returns a success response without
    starting a second instance. The watcher monitors WATCH_FOLDER from
    settings and syncs changes to storage + embeddings automatically.

    Returns:
        A dict with success=True and a status message.
    """
    global _watcher_thread, _watcher_observer

    with _watcher_lock:
        if _watcher_thread is not None and _watcher_thread.is_alive():
            return {"success": True, "message": "Watcher already running."}

        from watchdog.observers import Observer
        from api.services.watcher import PersonalCloudEventHandler

        watch_folder = settings.watch_folder_path
        if not watch_folder.exists():
            return {"success": False, "message": f"Watch folder does not exist: {watch_folder}"}

        handler = PersonalCloudEventHandler(
            on_sync=_sync_file_background,
            on_delete=_delete_file_background,
            supported_extensions=settings.SUPPORTED_EXTENSIONS,
        )

        observer = Observer()
        observer.schedule(handler, str(watch_folder), recursive=True)
        observer.start()
        _watcher_observer = observer

        def _run():
            """Thread target: keep the observer alive until stopped."""
            observer.join()

        thread = threading.Thread(target=_run, daemon=True, name="personalcloud-watcher")
        thread.start()
        _watcher_thread = thread

    return {"success": True, "message": f"Watcher started on {watch_folder}"}


@router.post("/watcher/stop", summary="Stop background file watcher")
def stop_watcher() -> dict:
    """
    Stop the background watchdog file system watcher thread.

    If the watcher is not running, returns success without error.

    Returns:
        A dict with success=True and a status message.
    """
    global _watcher_thread, _watcher_observer

    with _watcher_lock:
        if _watcher_observer is not None:
            try:
                _watcher_observer.stop()
                _watcher_observer.join(timeout=3)
            except Exception:
                pass
            _watcher_observer = None

        _watcher_thread = None

    return {"success": True, "message": "Watcher stopped."}
