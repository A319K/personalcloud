"""
database.py — SQLAlchemy engine and session management.

Uses a synchronous psycopg2 connection for simplicity. The DATABASE_URL
must point to a Neon (or any PostgreSQL) instance with the pgvector extension
already enabled.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from config.settings import settings


def get_engine():
    """
    Create and return a SQLAlchemy engine using the configured DATABASE_URL.

    Raises RuntimeError if DATABASE_URL is not configured.
    """
    if not settings.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured. Run `personalcloud init` to set it up."
        )

    # Convert asyncpg-style URLs to psycopg2-compatible if needed
    url = settings.DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    engine = create_engine(
        url,
        pool_pre_ping=True,   # verify connection health before using from pool
        pool_size=5,
        max_overflow=10,
        connect_args={"sslmode": "require"},
    )
    return engine


def get_session() -> Session:
    """
    Return a new SQLAlchemy Session bound to the configured engine.

    Callers are responsible for closing the session (use as context manager).
    """
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return SessionLocal()


def init_db() -> None:
    """
    Create all tables defined in db.models and ensure pgvector extension exists.

    Safe to call multiple times (uses CREATE IF NOT EXISTS semantics).
    """
    from db.models import Base  # local import to avoid circular deps

    engine = get_engine()

    # Ensure the pgvector extension is available
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    # Create all ORM-mapped tables
    Base.metadata.create_all(bind=engine)
