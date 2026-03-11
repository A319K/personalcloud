"""
search.py — FastAPI route for semantic search over synced files.

Endpoint:
  GET /search?q=your+query&top_k=5

Embeds the query using sentence-transformers and runs a cosine similarity
search over all file embeddings stored in pgvector.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from db.database import get_session
from api.services.embeddings import semantic_search

router = APIRouter(prefix="/search", tags=["search"])


def _get_db():
    """FastAPI dependency that yields a database session and closes it after the request."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@router.get("/", summary="Semantic search across all synced files")
def search_files(
    q: str = Query(..., max_length=500, description="Natural language search query"),
    top_k: int = Query(5, ge=1, le=50, description="Number of results to return"),
    db: Session = Depends(_get_db),
) -> dict:
    """
    Perform a natural language semantic search across all indexed files.

    Embeds the query using all-MiniLM-L6-v2 and returns the top-k most
    semantically similar files ranked by cosine similarity.

    Args:
        q: The search query string.
        top_k: How many results to return (1–50, default 5).

    Returns:
        A dict with "query", "count", and "results" (list of file matches).

    Raises:
        HTTPException 400: If the query is empty.
        HTTPException 500: If the search fails unexpectedly.
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        results = semantic_search(session=db, query=q, top_k=top_k)
    except Exception:
        raise HTTPException(status_code=500, detail="Search failed. Please try again.")

    return {
        "query": q,
        "count": len(results),
        "results": results,
    }
