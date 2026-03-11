"""
watcher.py — Watchdog-based folder watcher that triggers syncing on file changes.

Uses the watchdog library to monitor the WATCH_FOLDER for file system events
(creation, modification, deletion) and calls the sync pipeline for changed files.
"""

import time
from pathlib import Path
from typing import Callable, Optional

from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    FileModifiedEvent,
    FileDeletedEvent,
    FileMovedEvent,
)
from rich.console import Console

from config.settings import settings

console = Console()


class PersonalCloudEventHandler(FileSystemEventHandler):
    """
    Watchdog event handler that reacts to file system changes in the watch folder.

    On file creation or modification, triggers the provided sync callback.
    On deletion, triggers the provided delete callback.
    On move/rename, deletes the old key and syncs the new path.
    """

    def __init__(
        self,
        on_sync: Callable[[Path], None],
        on_delete: Callable[[Path], None],
        supported_extensions: list[str],
    ) -> None:
        """
        Args:
            on_sync: Callback to invoke when a file should be synced (new/modified).
            on_delete: Callback to invoke when a file has been deleted.
            supported_extensions: List of extensions to monitor (e.g. ['.pdf', '.txt']).
        """
        super().__init__()
        self._on_sync = on_sync
        self._on_delete = on_delete
        self._supported_extensions = set(ext.lower() for ext in supported_extensions)

    def _is_supported(self, path_str: str) -> bool:
        """Return True if the file extension is in the supported list."""
        return Path(path_str).suffix.lower() in self._supported_extensions

    def on_created(self, event: FileCreatedEvent) -> None:
        """Handle new file creation."""
        if not event.is_directory and self._is_supported(event.src_path):
            file_path = Path(event.src_path)
            console.print(f"[green]+[/green] New file detected: [bold]{file_path.name}[/bold]")
            self._on_sync(file_path)

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Handle file modification."""
        if not event.is_directory and self._is_supported(event.src_path):
            file_path = Path(event.src_path)
            console.print(f"[yellow]~[/yellow] Modified: [bold]{file_path.name}[/bold]")
            self._on_sync(file_path)

    def on_deleted(self, event: FileDeletedEvent) -> None:
        """Handle file deletion."""
        if not event.is_directory and self._is_supported(event.src_path):
            file_path = Path(event.src_path)
            console.print(f"[red]-[/red] Deleted: [bold]{file_path.name}[/bold]")
            self._on_delete(file_path)

    def on_moved(self, event: FileMovedEvent) -> None:
        """Handle file move or rename — delete old, sync new."""
        if not event.is_directory:
            old_path = Path(event.src_path)
            new_path = Path(event.dest_path)

            if self._is_supported(str(old_path)):
                console.print(f"[yellow]→[/yellow] Moved: {old_path.name} → {new_path.name}")
                self._on_delete(old_path)

            if self._is_supported(str(new_path)):
                self._on_sync(new_path)


def start_watcher(
    on_sync: Callable[[Path], None],
    on_delete: Callable[[Path], None],
) -> None:
    """
    Start the watchdog observer and block indefinitely, watching WATCH_FOLDER.

    Call this from the CLI `personalcloud watch` command. It runs in the
    foreground and can be interrupted with Ctrl+C.

    Args:
        on_sync: Function to call when a file should be synced.
        on_delete: Function to call when a file has been deleted.
    """
    watch_folder = settings.watch_folder_path

    if not watch_folder.exists():
        raise FileNotFoundError(f"Watch folder does not exist: {watch_folder}")

    handler = PersonalCloudEventHandler(
        on_sync=on_sync,
        on_delete=on_delete,
        supported_extensions=settings.SUPPORTED_EXTENSIONS,
    )

    observer = Observer()
    # recursive=True watches all subdirectories
    observer.schedule(handler, str(watch_folder), recursive=True)
    observer.start()

    console.print(
        f"\n[bold green]Watching[/bold green] [cyan]{watch_folder}[/cyan] for changes…"
    )
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        console.print("\n[yellow]Watcher stopped.[/yellow]")

    observer.join()
