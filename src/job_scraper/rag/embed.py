
import sqlite3

import numpy as np
import voyageai

from job_scraper.rag.prepare import compose_embed_text

MODEL = "voyage-3.5-lite"
DIM = 1024
BATCH_SIZE = 128

# columns compose_embed_text needs, plus id for the UPDATE
_SELECT_COLS = (
    "id, title, company, locations, employment_type, "
    "skills, salary_min, salary_max, currency, description"
)


def vec_to_blob(vec) -> bytes:
    """float32 pack — the storage contract. 1024 floats -> 4096 bytes."""
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_vec(blob: bytes) -> np.ndarray:
    """float32 unpack — inverse of vec_to_blob. dtype MUST match."""
    return np.frombuffer(blob, dtype=np.float32)


def embed_pending(db_path: str = "jobs.db", batch_size: int = BATCH_SIZE) -> int:
    """Embed every row where embedding IS NULL. Resumable: rerun continues
    from wherever it stopped. Returns count embedded this run."""
    vo = voyageai.Client()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        f"SELECT {_SELECT_COLS} FROM jobs WHERE embedding IS NULL"
    ).fetchall()

    if not rows:
        print("nothing to embed — all rows have vectors")
        conn.close()
        return 0

    print(f"{len(rows)} rows to embed, batch_size={batch_size}")
    total_embedded = 0

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [compose_embed_text(r) for r in batch]

        result = vo.embed(texts, model=MODEL, input_type="document")

        # write vectors back, keyed by id, in one transaction per batch
        updates = [
            (vec_to_blob(vec), MODEL, r["id"])
            for r, vec in zip(batch, result.embeddings)
        ]
        conn.executemany(
            "UPDATE jobs SET embedding = ?, embedding_model = ? WHERE id = ?",
            updates,
        )
        conn.commit()  # commit per batch => crash-safe resume boundary

        total_embedded += len(batch)
        print(
            f"  embedded {total_embedded}/{len(rows)} "
            f"(+{result.total_tokens} tokens)"
        )

    conn.close()
    print(f"done — embedded {total_embedded} rows")
    return total_embedded


if __name__ == "__main__":
    embed_pending()
