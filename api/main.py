"""
api/main.py — FastAPI application entry point.

Mounts all routers and sets up startup/shutdown lifecycle events.
The CLI communicates with this API over HTTP (localhost by default).
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from rich.console import Console

from api.routes.files import router as files_router
from api.routes.search import router as search_router
from api.routes.status import router as status_router

console = Console(stderr=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.

    Runs startup logic (DB init) before the app starts serving requests,
    and cleanup logic on shutdown.
    """
    # Startup: ensure DB tables exist
    try:
        from db.database import init_db
        init_db()
        console.print("[green]✓[/green] Database initialized.")
    except Exception as e:
        console.print(f"[red]✗ Database init failed:[/red] {e}")
        raise

    yield  # app runs here

    # Shutdown cleanup (nothing special needed for now)
    console.print("[dim]API server shutting down.[/dim]")


app = FastAPI(
    title="personalcloud API",
    description="Backend API for the personalcloud CLI — handles file syncing and semantic search.",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount routers
app.include_router(files_router)
app.include_router(search_router)
app.include_router(status_router)


@app.get("/", tags=["health"])
def health_check() -> dict:
    """
    Health check endpoint.

    Returns:
        A dict confirming the API is running.
    """
    return {"status": "ok", "service": "personalcloud"}


@app.get("/health", tags=["health"])
def health() -> dict:
    """
    Detailed health check — verifies DB connectivity.

    Returns:
        A dict with status and any errors encountered.
    """
    from db.database import get_session
    try:
        from sqlalchemy import text
        session = get_session()
        session.execute(text("SELECT 1"))
        session.close()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
    }
