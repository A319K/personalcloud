"""
cli/main.py — personalcloud CLI built with Typer.

Commands:
  init    — Interactive setup wizard (storage backend, watch folder, .env writing)
  sync    — Full sync of the watch folder to storage + generate embeddings
  watch   — Start live file watcher (auto-syncs on change)
  search  — Natural language search across all synced files
  status  — Show sync statistics
  ls      — List all synced files
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import print as rprint

app = typer.Typer(
    name="personalcloud",
    help="Self-hosted AI-powered personal cloud backup and search.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)

# Path to .env file in the project root
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_settings():
    """
    Reload and return the settings object after .env changes.

    Always re-imports to pick up any env vars written during `init`.
    """
    import importlib
    import config.settings as _s
    importlib.reload(_s)
    return _s.settings


def _write_env(values: dict[str, str]) -> None:
    """
    Write or update key=value pairs in the .env file.

    Reads existing lines and updates in-place so comments are preserved.
    New keys are appended at the end.

    Args:
        values: Dict of env var names to new string values.
    """
    existing_lines: list[str] = []
    if _ENV_PATH.exists():
        existing_lines = _ENV_PATH.read_text().splitlines()

    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue

        key = stripped.split("=", 1)[0].strip()
        if key in values:
            new_lines.append(f"{key}={values[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    # Append any keys not already present
    for key, val in values.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    _ENV_PATH.write_text("\n".join(new_lines) + "\n")


def _ensure_configured() -> None:
    """
    Check that the .env file exists and DATABASE_URL is set.

    Exits with a friendly error message if not configured.
    """
    if not _ENV_PATH.exists():
        err_console.print(
            "[red]✗[/red] No .env file found. Run [bold]personalcloud init[/bold] first."
        )
        raise typer.Exit(1)

    settings = _load_settings()
    errors = settings.validate()
    if errors:
        err_console.print("[red]✗ Configuration errors:[/red]")
        for e in errors:
            err_console.print(f"  • {e}")
        err_console.print("\nRun [bold]personalcloud init[/bold] to fix these.")
        raise typer.Exit(1)


def _sync_file(file_path: Path, watch_folder: Path, settings) -> bool:
    """
    Sync a single file: upload to storage, extract text, store embedding.

    Checks whether the file has changed since last sync using its last-modified
    timestamp. Skips unchanged files to avoid redundant work.

    Args:
        file_path: Absolute path to the file to sync.
        watch_folder: The root watch folder (used to compute storage_key).
        settings: The loaded settings object.

    Returns:
        True if the file was synced (new or changed), False if it was skipped.
    """
    from db.database import get_session
    from db.models import SyncedFile
    from api.services.storage import StorageService, StorageError
    from api.services.ocr import extract_text
    from api.services.embeddings import generate_embedding, store_embedding
    from datetime import datetime

    # Compute storage key relative to the watch folder
    try:
        storage_key = str(file_path.relative_to(watch_folder))
    except ValueError:
        storage_key = file_path.name

    # Get current file stats
    stat = file_path.stat()
    current_mtime = int(stat.st_mtime)
    current_size = stat.st_size

    # Skip files larger than 500 MB to avoid OOM issues
    MAX_FILE_SIZE = 500 * 1024 * 1024
    if current_size > MAX_FILE_SIZE:
        err_console.print(f"[yellow]Skipping {file_path.name}:[/yellow] file exceeds 500 MB limit.")
        return False

    session = get_session()
    try:
        existing = session.query(SyncedFile).filter_by(local_path=str(file_path)).first()

        # Skip if file hasn't changed since last sync
        if existing and existing.last_modified_ts == current_mtime:
            return False  # unchanged

        # Upload to storage
        storage = StorageService()
        storage.upload_file(file_path, storage_key)

        # Extract text from the file
        text = extract_text(file_path)

        # Generate embedding
        embedding_vector = generate_embedding(text)

        if existing:
            # Update existing record
            existing.storage_key = storage_key
            existing.file_size = current_size
            existing.last_modified_ts = current_mtime
            existing.updated_at = datetime.utcnow()
            session.commit()
            file_id = existing.id
        else:
            # Insert new record
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

        # Store or update embedding
        store_embedding(session, file_id, text, embedding_vector)
        return True

    except StorageError as e:
        err_console.print(f"[red]✗ Storage error for {file_path.name}:[/red] {e}")
        return False
    except Exception as e:
        err_console.print(f"[red]✗ Failed to sync {file_path.name}:[/red] {e}")
        return False
    finally:
        session.close()


def _delete_file_record(file_path: Path) -> None:
    """
    Remove a deleted file's records from the database and storage.

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

        # Remove from storage
        try:
            storage = StorageService()
            storage.delete_file(record.storage_key)
        except StorageError as e:
            err_console.print(f"[yellow]Warning:[/yellow] Could not delete from storage: {e}")

        session.delete(record)
        session.commit()
    except Exception as e:
        err_console.print(f"[red]✗ Failed to delete record for {file_path.name}:[/red] {e}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def init() -> None:
    """
    Interactive setup wizard.

    Walks through storage backend choice, credentials, watch folder, and
    database connection. Writes all values to the .env file in the project root.
    Also initializes the database tables.
    """
    console.print(Panel.fit(
        "[bold cyan]personalcloud[/bold cyan] — Setup Wizard",
        subtitle="Press Enter to accept defaults shown in [dim][brackets][/dim]",
    ))
    console.print()

    env_values: dict[str, str] = {}

    # --- Storage backend ---
    backend = typer.prompt(
        "Storage backend",
        default="minio",
        prompt_suffix=" [r2/minio]: ",
    ).strip().lower()

    while backend not in ("r2", "minio"):
        console.print("[red]Please enter 'r2' or 'minio'.[/red]")
        backend = typer.prompt("Storage backend", default="minio", prompt_suffix=" [r2/minio]: ").strip().lower()

    env_values["STORAGE_BACKEND"] = backend

    if backend == "r2":
        console.print("\n[bold]Cloudflare R2 credentials[/bold]")
        console.print("Find these in: Cloudflare Dashboard → R2 → Manage R2 API Tokens\n")
        env_values["R2_ACCOUNT_ID"] = typer.prompt("R2 Account ID").strip()
        env_values["R2_ACCESS_KEY_ID"] = typer.prompt("R2 Access Key ID").strip()
        env_values["R2_SECRET_ACCESS_KEY"] = typer.prompt("R2 Secret Access Key", hide_input=True).strip()
        env_values["R2_BUCKET_NAME"] = typer.prompt("R2 Bucket Name", default="personalcloud").strip()
    else:
        console.print("\n[bold]MinIO configuration[/bold]")
        console.print("[dim]Run `docker compose up -d` to start MinIO if not already running.[/dim]\n")
        env_values["MINIO_ENDPOINT"] = typer.prompt("MinIO endpoint", default="http://localhost:9000").strip()
        env_values["MINIO_ACCESS_KEY"] = typer.prompt("MinIO access key", default="minioadmin").strip()
        env_values["MINIO_SECRET_KEY"] = typer.prompt("MinIO secret key", default="minioadmin", hide_input=True).strip()
        env_values["MINIO_BUCKET_NAME"] = typer.prompt("MinIO bucket name", default="personalcloud").strip()

    # --- Watch folder ---
    console.print("\n[bold]Watch folder[/bold]")
    default_folder = str(Path.home() / "Documents")
    watch_folder = typer.prompt("Folder to watch and sync", default=default_folder).strip()
    watch_path = Path(watch_folder).expanduser()

    if not watch_path.exists():
        create = typer.confirm(f"Folder {watch_path} doesn't exist. Create it?", default=True)
        if create:
            watch_path.mkdir(parents=True)
            console.print(f"[green]✓[/green] Created {watch_path}")
        else:
            console.print("[yellow]Warning:[/yellow] Watch folder does not exist. Update WATCH_FOLDER in .env later.")

    env_values["WATCH_FOLDER"] = str(watch_path)

    # --- Database ---
    console.print("\n[bold]Database (Neon PostgreSQL)[/bold]")
    console.print("[dim]Get your connection string from: https://console.neon.tech[/dim]")
    console.print("[dim]Format: postgresql://user:pass@host/dbname?sslmode=require[/dim]\n")

    db_url = typer.prompt("Neon DATABASE_URL").strip()
    env_values["DATABASE_URL"] = db_url

    # Write .env
    _write_env(env_values)
    console.print(f"\n[green]✓[/green] Configuration saved to [bold]{_ENV_PATH}[/bold]")

    # Reload settings and init DB
    console.print("\n[dim]Initializing database tables…[/dim]")
    try:
        # Set env var immediately for this process
        os.environ["DATABASE_URL"] = db_url
        from db.database import init_db
        init_db()
        console.print("[green]✓[/green] Database tables created.")
    except Exception as e:
        err_console.print(f"[red]✗ Database initialization failed:[/red] {e}")
        err_console.print("Check your DATABASE_URL and try running [bold]personalcloud sync[/bold] again.")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        "[green]Setup complete![/green]\n\n"
        "Next steps:\n"
        "  • [bold]personalcloud sync[/bold]  — sync your files now\n"
        "  • [bold]personalcloud watch[/bold]  — start live file watching\n"
        "  • [bold]personalcloud search \"your query\"[/bold]  — search your files",
        title="Ready",
        expand=False,
    ))


@app.command()
def sync() -> None:
    """
    Perform a full sync of the watch folder to cloud/local storage.

    Walks all supported files in WATCH_FOLDER, skips unchanged files,
    uploads changed/new files, and generates embeddings for search.
    """
    _ensure_configured()
    settings = _load_settings()
    watch_folder = settings.watch_folder_path

    console.print(f"\n[bold cyan]Syncing[/bold cyan] [white]{watch_folder}[/white]\n")

    if not watch_folder.exists():
        err_console.print(f"[red]✗[/red] Watch folder not found: {watch_folder}")
        raise typer.Exit(1)

    # Collect all files with supported extensions
    all_files: list[Path] = []
    for ext in settings.SUPPORTED_EXTENSIONS:
        all_files.extend(watch_folder.rglob(f"*{ext}"))

    if not all_files:
        console.print("[yellow]No supported files found in watch folder.[/yellow]")
        return

    synced = 0
    skipped = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Syncing files…", total=len(all_files))

        for file_path in all_files:
            progress.update(task, description=f"[dim]{file_path.name[:40]}[/dim]")
            try:
                result = _sync_file(file_path, watch_folder, settings)
                if result:
                    synced += 1
                else:
                    skipped += 1
            except Exception as e:
                err_console.print(f"[red]✗[/red] {file_path.name}: {e}")
                failed += 1
            finally:
                progress.advance(task)

    # Summary table
    table = Table(title="Sync Complete", show_header=False, box=None)
    table.add_row("[green]Synced[/green]", str(synced))
    table.add_row("[dim]Skipped (unchanged)[/dim]", str(skipped))
    if failed:
        table.add_row("[red]Failed[/red]", str(failed))

    console.print()
    console.print(table)


@app.command()
def watch() -> None:
    """
    Start a live file watcher on the WATCH_FOLDER.

    Monitors for new, modified, or deleted files and automatically syncs them.
    Runs in the foreground — press Ctrl+C to stop.
    """
    _ensure_configured()
    settings = _load_settings()

    # Run an initial full sync before starting the watcher
    console.print("[dim]Running initial sync before starting watcher…[/dim]")
    sync()

    from api.services.watcher import start_watcher

    def on_sync(file_path: Path) -> None:
        """Callback invoked by the watcher when a file is created or modified."""
        _sync_file(file_path, settings.watch_folder_path, settings)

    def on_delete(file_path: Path) -> None:
        """Callback invoked by the watcher when a file is deleted."""
        _delete_file_record(file_path)

    try:
        start_watcher(on_sync=on_sync, on_delete=on_delete)
    except FileNotFoundError as e:
        err_console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)


@app.command()
def search(
    query: str = typer.Argument(..., help="Natural language search query"),
    top_k: int = typer.Option(5, "--top", "-n", help="Number of results to return", min=1, max=50),
) -> None:
    """
    Semantic search across all synced files using natural language.

    Embeds your query locally (no API calls) and finds the most relevant
    files using cosine similarity against stored pgvector embeddings.
    """
    _ensure_configured()

    console.print(f"\n[bold cyan]Searching:[/bold cyan] [italic]{query}[/italic]\n")

    from db.database import get_session
    from api.services.embeddings import semantic_search

    session = get_session()
    try:
        results = semantic_search(session=session, query=query, top_k=top_k)
    except Exception as e:
        err_console.print(f"[red]✗ Search failed:[/red] {e}")
        raise typer.Exit(1)
    finally:
        session.close()

    if not results:
        console.print("[yellow]No results found.[/yellow] Try syncing first with [bold]personalcloud sync[/bold].")
        return

    for i, result in enumerate(results, start=1):
        similarity_pct = f"{result['similarity'] * 100:.1f}%"
        score_color = "green" if result["similarity"] > 0.7 else "yellow" if result["similarity"] > 0.4 else "red"

        console.print(
            f"[bold]{i}.[/bold] [white]{result['filename']}[/white]  "
            f"[{score_color}]{similarity_pct} match[/{score_color}]"
        )
        console.print(f"   [dim]{result['local_path']}[/dim]")

        snippet = result.get("snippet", "").replace("\n", " ").strip()
        if snippet:
            # Truncate snippet for display
            display_snippet = snippet[:200] + ("…" if len(snippet) > 200 else "")
            console.print(f"   [italic dim]{display_snippet}[/italic dim]")

        console.print()


@app.command()
def status() -> None:
    """
    Show sync statistics: total files, storage used, backend, watch folder.
    """
    _ensure_configured()
    settings = _load_settings()

    from db.database import get_session
    from db.models import SyncedFile, FileEmbedding
    from sqlalchemy import func

    session = get_session()
    try:
        total_files = session.query(func.count(SyncedFile.id)).scalar() or 0
        total_size_bytes = session.query(func.sum(SyncedFile.file_size)).scalar() or 0
        embedded_files = session.query(func.count(FileEmbedding.id)).scalar() or 0
    except Exception as e:
        err_console.print(f"[red]✗ Could not fetch status:[/red] {e}")
        raise typer.Exit(1)
    finally:
        session.close()

    # Human-readable size
    def fmt_size(n: int) -> str:
        """Format bytes into a human-readable string."""
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"

    table = Table(title="personalcloud Status", show_header=False, box=None, padding=(0, 2))
    table.add_row("[cyan]Storage backend[/cyan]", settings.STORAGE_BACKEND.upper())
    table.add_row("[cyan]Bucket[/cyan]", settings.bucket_name)
    table.add_row("[cyan]Watch folder[/cyan]", str(settings.watch_folder_path))
    table.add_row("[cyan]Total synced files[/cyan]", str(total_files))
    table.add_row("[cyan]Files with embeddings[/cyan]", str(embedded_files))
    table.add_row("[cyan]Total storage used[/cyan]", fmt_size(total_size_bytes))

    console.print()
    console.print(table)
    console.print()


@app.command(name="ls")
def list_files() -> None:
    """
    List all synced files with their paths and sizes.
    """
    _ensure_configured()

    from db.database import get_session
    from db.models import SyncedFile

    session = get_session()
    try:
        files = session.query(SyncedFile).order_by(SyncedFile.filename).all()
    except Exception as e:
        err_console.print(f"[red]✗ Could not list files:[/red] {e}")
        raise typer.Exit(1)
    finally:
        session.close()

    if not files:
        console.print("[yellow]No files synced yet.[/yellow] Run [bold]personalcloud sync[/bold] first.")
        return

    def fmt_size(n: int) -> str:
        """Format bytes into a human-readable string."""
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} GB"

    table = Table(title=f"Synced Files ({len(files)} total)", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Filename", style="bold white")
    table.add_column("Ext", style="cyan", width=6)
    table.add_column("Size", style="green", justify="right", width=10)
    table.add_column("Path", style="dim")

    for i, f in enumerate(files, start=1):
        table.add_row(
            str(i),
            f.filename,
            f.extension,
            fmt_size(f.file_size),
            f.local_path,
        )

    console.print()
    console.print(table)
    console.print()


if __name__ == "__main__":
    app()
