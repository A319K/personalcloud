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


def store_chunks(
    session: Session,
    file_id: int,
    text: str,
    filename: str,
    chunk_size: int = 800,
    overlap: int = 150,
) -> None:
    """
    Split text into overlapping chunks and store one embedding per chunk.

    This bypasses the model's ~256-token (~1000-char) input limit: instead of
    embedding a truncated version of the whole file, we embed each 800-char
    window so that content anywhere in the document is captured.

    The first chunk always has ``Filename: <name>`` prepended so that file-name
    keywords influence the embedding even if they don't appear in the body text.

    Existing chunks for this file_id are deleted and replaced on every call
    (i.e. a full re-embed on each sync of a changed file).

    Args:
        session: Active SQLAlchemy session.
        file_id: PK of the SyncedFile these chunks belong to.
        text: Full extracted text for the file.
        filename: Original filename (e.g. "dijkstra_notes.pdf") prepended to chunk 0.
        chunk_size: Characters per chunk. 800 is comfortably within the 256-token limit.
        overlap: Characters of overlap between consecutive chunks for context continuity.
    """
    from db.models import FileEmbedding

    # Delete all existing chunks so a re-sync starts clean
    session.query(FileEmbedding).filter_by(file_id=file_id).delete()
    session.flush()

    # Build chunk boundaries
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        start += chunk_size - overlap
        if start >= len(text):
            break
    # Always have at least one chunk (handles empty-text files)
    if not chunks:
        chunks = [""]

    for i, chunk in enumerate(chunks):
        # Prepend filename to the first chunk so file-name keywords are embedded
        text_for_model = (f"Filename: {filename}\n\n{chunk}" if i == 0 else chunk)
        vector = generate_embedding(text_for_model)
        session.add(
            FileEmbedding(
                file_id=file_id,
                chunk_index=i,
                extracted_text=chunk,  # store without prefix for clean snippet display
                embedding=vector,
            )
        )

    session.commit()


def semantic_search(
    session: Session,
    query: str,
    top_k: int = 5,
    min_similarity: float = 0.30,
) -> list[dict]:
    """
    Hybrid semantic + keyword search over stored embeddings.

    Combines two signals:
      1. Semantic similarity — cosine distance between query and file embeddings
         (all-MiniLM-L6-v2, 384-dim). Good for concept-level matching.
      2. Keyword boost (+0.20) — PostgreSQL full-text search that checks if the
         query terms literally appear in the extracted text or filename.
         Critical for proper nouns (names, algorithms, acronyms) that the
         semantic model doesn't map well on its own.

    Results below min_similarity on both signals are filtered out to avoid
    surfacing unrelated files when no good match exists.

    Args:
        session: Active SQLAlchemy session.
        query: Natural language or keyword search string.
        top_k: Maximum number of results to return (default: 5).
        min_similarity: Minimum semantic score to include a result that has
            no keyword match. Defaults to 0.30.

    Returns:
        A list of dicts with filename, local_path, similarity, snippet, id, extension.
    """
    from sqlalchemy import text as sql_text

    query_vector = generate_embedding(query)

    # Format vector for pgvector: '[0.1, 0.2, ...]'
    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    # Hybrid query with per-file deduplication:
    #
    # Inner query: score every chunk with semantic + keyword boost, pick the
    #   best chunk per file using DISTINCT ON (file_id ORDER BY score DESC).
    # Outer query: filter by min_sim / keyword match, sort, limit.
    #
    # The keyword boost (+0.20) ensures that files literally containing the
    # query term (e.g. "dijkstra") surface even when semantic similarity is
    # moderate, which is important for proper nouns and technical terms.
    raw_sql = sql_text(
        """
        SELECT *
        FROM (
            SELECT DISTINCT ON (sf.id)
                sf.id,
                sf.filename,
                sf.local_path,
                sf.extension,
                fe.extracted_text,
                LEAST(
                    (1 - (fe.embedding <=> CAST(:vec AS vector)))
                    + CASE
                        WHEN to_tsvector('english',
                                 COALESCE(fe.extracted_text, '') || ' ' || sf.filename)
                             @@ plainto_tsquery('english', :query_text)
                        THEN 0.20
                        ELSE 0.0
                      END,
                    1.0
                ) AS similarity
            FROM file_embeddings fe
            JOIN synced_files sf ON sf.id = fe.file_id
            WHERE fe.embedding IS NOT NULL
            ORDER BY sf.id,
                     (1 - (fe.embedding <=> CAST(:vec AS vector)))
                     + CASE
                         WHEN to_tsvector('english',
                                  COALESCE(fe.extracted_text, '') || ' ' || sf.filename)
                              @@ plainto_tsquery('english', :query_text)
                         THEN 0.20
                         ELSE 0.0
                       END DESC
        ) best_chunk
        WHERE similarity >= :min_sim
           OR to_tsvector('english',
                  COALESCE(extracted_text, '') || ' ' || filename)
              @@ plainto_tsquery('english', :query_text)
        ORDER BY similarity DESC
        LIMIT :top_k
        """
    )

    rows = session.execute(
        raw_sql,
        {
            "vec": vector_str,
            "query_text": query,
            "min_sim": min_similarity,
            "top_k": top_k,
        },
    ).fetchall()

    results: list[dict] = []
    for row in rows:
        snippet = (row.extracted_text or "")[:300]
        results.append(
            {
                "filename": row.filename,
                "local_path": row.local_path,
                "similarity": round(float(row.similarity), 4),
                "snippet": snippet,
                "id": str(row.id),
                "extension": row.extension,
            }
        )

    return results
