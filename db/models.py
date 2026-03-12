"""
models.py — SQLAlchemy ORM models for personalcloud.

Tables:
  - synced_files: tracks every file that has been uploaded to storage
  - file_embeddings: stores the 384-dim sentence-transformer vector per file
"""

from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    BigInteger,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class SyncedFile(Base):
    """
    Represents a file that has been synced to cloud/local storage.

    Tracks the file path, a stable storage key, the last-modified timestamp
    at the time of sync (used to detect changes), and the size in bytes.
    """

    __tablename__ = "synced_files"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Absolute local path of the file (e.g. /Users/aiden/Documents/notes.md)
    local_path = Column(String(4096), nullable=False, unique=True)

    # Key used in the storage bucket (relative path from watch folder root)
    storage_key = Column(String(4096), nullable=False)

    # Filename for display
    filename = Column(String(512), nullable=False)

    # File extension (e.g. ".pdf")
    extension = Column(String(32), nullable=False)

    # Size in bytes at time of last sync
    file_size = Column(BigInteger, nullable=False, default=0)

    # Last-modified Unix timestamp at the time of last sync (used for change detection)
    last_modified_ts = Column(BigInteger, nullable=False, default=0)

    # When this record was first created / last updated in our DB
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationship to embedding chunks (one-to-many after chunking migration)
    chunks = relationship(
        "FileEmbedding",
        back_populates="file",
        uselist=True,
        order_by="FileEmbedding.chunk_index",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<SyncedFile id={self.id} path={self.local_path!r}>"


class FileEmbedding(Base):
    """
    Stores one embedding chunk for a synced file.

    A single file may have multiple rows (chunk_index 0, 1, 2…) so that long
    documents are fully covered. The model input limit (~256 tokens / ~1000 chars)
    means a single embedding only captures the first ~1000 chars of a file;
    chunking ensures content deeper in the document is searchable.
    """

    __tablename__ = "file_embeddings"
    __table_args__ = (
        UniqueConstraint("file_id", "chunk_index", name="uq_file_chunk"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # FK to the parent synced file
    file_id = Column(Integer, ForeignKey("synced_files.id", ondelete="CASCADE"), nullable=False)

    # 0-based position of this chunk within the file
    chunk_index = Column(Integer, nullable=False, default=0)

    # Raw text of this chunk (stored as-is for snippet display, without filename prefix)
    extracted_text = Column(Text, nullable=True)

    # 384-dimensional embedding vector from all-MiniLM-L6-v2
    embedding = Column(Vector(384), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Back-reference to SyncedFile
    file = relationship("SyncedFile", back_populates="chunks")

    def __repr__(self) -> str:
        return f"<FileEmbedding file_id={self.file_id} chunk={self.chunk_index}>"
