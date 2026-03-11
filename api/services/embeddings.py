"""
embeddings.py — Embedding generation and semantic search using sentence-transformers.

Model: all-MiniLM-L6-v2 (384-dimensional output, runs fully locally, no API keys needed).

This module handles:
  1. Loading and caching the model singleton
  2. Generating embeddings for a text string
  3. Storing an embedding in the database for a given file
  4. Running cosine-similarity search against stored embeddings
"""

from __future__ import annotations

from typing import Optional
from pathlib import Path

from rich.console import Console
from sqlalchemy.orm import Session

console = Console(stderr=True)

# Model name — change here to swap models project-wide
_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None  # lazy-loaded singleton


def _get_model():
    """
    Load and return the sentence-transformers model, caching it as a module-level singleton.

    Lazy-loads on first call so the CLI starts fast even if the model isn't needed.

    Returns:
        A SentenceTransformer instance ready for .encode() calls.
    """
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        console.print(f"[dim]Loading embedding model ({_MODEL_NAME})…[/dim]")
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def generate_embedding(text: str) -> list[float]:
    """
    Generate a 384-dimensional embedding vector for the given text.

    Args:
        text: The input text to embed. Empty strings produce a zero-vector.

    Returns:
        A list of 384 floats representing the semantic embedding.
    """
    if not text.strip():
        # Return a zero vector for empty text — won't match well in cosine search
        return [0.0] * 384

    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def store_embedding(
    session: Session,
    file_id: int,
    text: str,
    embedding_vector: list[float],
) -> None:
    """
    Upsert (insert or update) the embedding record for a given file in the database.

    If a FileEmbedding row already exists for this file_id, it is updated.
    Otherwise, a new row is inserted.

    Args:
        session: Active SQLAlchemy session.
        file_id: PK of the SyncedFile this embedding belongs to.
        text: The extracted text (stored as a snippet for search results).
        embedding_vector: The 384-dim float list from generate_embedding().
    """
    from db.models import FileEmbedding

    existing = session.query(FileEmbedding).filter_by(file_id=file_id).first()

    if existing:
        existing.extracted_text = text
        existing.embedding = embedding_vector
    else:
        record = FileEmbedding(
            file_id=file_id,
            extracted_text=text,
            embedding=embedding_vector,
        )
        session.add(record)

    session.commit()


def semantic_search(
    session: Session,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Embed the query and perform a cosine similarity search over all stored embeddings.

    Uses pgvector's <=> operator (cosine distance) to find the most semantically
    similar files to the query.

    Args:
        session: Active SQLAlchemy session.
        query: Natural language search query from the user.
        top_k: Number of top results to return (default: 5).

    Returns:
        A list of dicts, each containing:
            - filename (str)
            - local_path (str)
            - similarity (float, 0–1, higher = more relevant)
            - snippet (str, first 300 chars of extracted text)
    """
    from sqlalchemy import text as sql_text
    from db.models import SyncedFile, FileEmbedding

    query_vector = generate_embedding(query)

    # Format vector for pgvector: '[0.1, 0.2, ...]'
    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    # Cosine similarity = 1 - cosine_distance
    # pgvector's <=> operator returns cosine distance (0=identical, 2=opposite)
    raw_sql = sql_text(
        """
        SELECT
            sf.id,
            sf.filename,
            sf.local_path,
            fe.extracted_text,
            1 - (fe.embedding <=> CAST(:vec AS vector)) AS similarity
        FROM file_embeddings fe
        JOIN synced_files sf ON sf.id = fe.file_id
        WHERE fe.embedding IS NOT NULL
        ORDER BY fe.embedding <=> CAST(:vec AS vector)
        LIMIT :top_k
        """
    )

    rows = session.execute(raw_sql, {"vec": vector_str, "top_k": top_k}).fetchall()

    results: list[dict] = []
    for row in rows:
        snippet = (row.extracted_text or "")[:300]
        results.append(
            {
                "filename": row.filename,
                "local_path": row.local_path,
                "similarity": round(float(row.similarity), 4),
                "snippet": snippet,
            }
        )

    return results
