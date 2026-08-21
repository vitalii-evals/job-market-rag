import sqlite3

import numpy as np
import voyageai

from job_scraper.rag.embed import blob_to_vec, MODEL, DIM

# columns the answer layer will want alongside each retrieved vector
_META_COLS = [
    "id", "title", "company", "locations", "url", "match_tier",
    "salary_min", "salary_max", "currency", "salary_period", "location_type",
    "experience_level", "skills", "posted_date", "employment_type", "description",
]

def load_vector_store(db_path: str = "jobs.db"):
    """Load all embedded jobs into an in-RAM matrix + aligned metadata.
    Returns (matrix, metadata) where matrix[i] corresponds to metadata[i].
    Only rows WHERE embedding IS NOT NULL are included."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cols = ", ".join(_META_COLS)
    rows = conn.execute(
        f"SELECT {cols}, embedding FROM jobs WHERE embedding IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        raise RuntimeError("no embedded rows — run embed.py first")

    # stack vectors into one (N, DIM) float32 matrix
    matrix = np.vstack([blob_to_vec(r["embedding"]) for r in rows])
    metadata = [{k: r[k] for k in _META_COLS} for r in rows]
    return matrix, metadata


def embed_query(text: str) -> np.ndarray:
    """Embed a search query. input_type='query' — the OTHER half of the
    asymmetric pair; documents were embedded with input_type='document'."""
    vo = voyageai.Client()
    result = vo.embed([text], model=MODEL, input_type="query")
    return np.asarray(result.embeddings[0], dtype=np.float32)


def search(query: str, k: int = 5, db_path: str = "jobs.db"):
    """Retrieve top-k jobs by cosine similarity to the query.
    Because all vectors are L2-normalized (Voyage guarantee), cosine
    similarity == dot product, so scores = matrix @ q in one op."""
    matrix, metadata = load_vector_store(db_path)
    q = embed_query(query)

    scores = matrix @ q                    # (N,) cosine sims, single matvec
    top_idx = np.argsort(scores)[::-1][:k] # descending, take k

    results = []
    for i in top_idx:
        results.append({**metadata[i], "score": float(scores[i])})
    return results


if __name__ == "__main__":
    import sys

    query = sys.argv[1] if len(sys.argv) > 1 else "senior LLM / RAG engineer, Python, remote"
    print(f'query: "{query}"\n')
    for rank, job in enumerate(search(query, k=8), 1):
        print(f"{rank}. [{job['score']:.4f}] {job['title']} @ {job['company']}")
        print(f"   {job['match_tier']} | {job['locations']} | {job['id']}")
