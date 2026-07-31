"""CV-matching: rank all embedded jobs by similarity to the CV.
Reuses retrieve.py's vector store + cosine; the CV is just a (long) query."""
import sys

import docx
import numpy as np

from job_scraper.rag.retrieve import load_vector_store, embed_query
from job_scraper.rag.answer import _format_salary

KRAKOW_SPELLINGS = ("kraków", "krakow", "cracow")


def _passes_location(job, krakow: bool = True, remote: bool = True) -> bool:
    """Keep a job if it's remote OR in Kraków (any spelling).
    krakow/remote flags let callers widen or narrow the gate."""
    if remote and job.get("location_type") == "remote":
        return True
    if krakow:
        locs = (job.get("locations") or "").lower()
        if any(city in locs for city in KRAKOW_SPELLINGS):
            return True
    return False

# Target line (shape B) — steers matching toward goal roles, not just past work.
# Lives here, NOT in the CV file, so tuning aim doesn't touch the real document.
TARGET_STATEMENT = (
    "Seeking: Python RAG, LLM, and AI-automation engineering roles with hands-on "
    "implementation - retrieval pipelines, embeddings, agent systems, and eval harnesses."
)


def read_cv(path: str = "cv.docx") -> str:
    """Extract CV text (paragraphs; this CV has no tables)."""
    doc = docx.Document(path)
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paras)


def build_cv_query(cv_path: str = "cv.docx") -> str:
    """CV text + target statement = the matching query (shape B)."""
    return read_cv(cv_path) + "\n\n" + TARGET_STATEMENT


def rank_jobs(cv_path: str = "cv.docx", top_n: int = 20, db_path: str = "jobs.db"):
    """Rank every embedded job by cosine similarity to the CV query, then
    collapse near-identical postings (same title+company across cities) into
    one entry. Returns top_n DISTINCT jobs, best first."""
    matrix, metadata = load_vector_store(db_path)   # (N, 1024) + aligned meta
    query = build_cv_query(cv_path)
    q = embed_query(query)                            # CV as a query vector

    scores = matrix @ q                              # cosine (vectors are unit-norm)
    order = np.argsort(scores)[::-1]                 # ALL jobs, descending

    # Walk highest-first: apply location gate, then dedupe (title, company).
    seen = {}          # (title, company) -> result dict
    distinct = []      # kept entries, in rank order
    for i in order:
        job = metadata[i]
        if not _passes_location(job):                # Kraków or remote only
            continue
        key = (job["title"], job["company"])
        if key in seen:
            # same role, different city — merge this location in
            entry = seen[key]
            loc = (job["locations"] or "").strip()
            if loc and loc not in entry["_locs"]:
                entry["_locs"].append(loc)
            continue
        entry = {**job, "score": float(scores[i]), "_locs": [(job["locations"] or "").strip()]}
        seen[key] = entry
        distinct.append(entry)
        if len(distinct) >= top_n:
            break

    # finalize merged locations into a display string
    for e in distinct:
        locs = [l for l in e["_locs"] if l]
        e["locations"] = ", ".join(locs) if locs else e.get("locations")
        del e["_locs"]

    return distinct



if __name__ == "__main__":
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    results = rank_jobs(top_n=top_n)

    print(f"Top {len(results)} distinct jobs matched to your CV:\n")
    for rank, job in enumerate(results, 1):
        sal = _format_salary(job)
        loc = job["locations"] or "location n/a"
        # if many cities merged, show count compactly
        city_count = loc.count(",") + 1 if loc != "location n/a" else 0
        loc_display = loc if city_count <= 3 else (
            ", ".join(loc.split(", ")[:3]) + f", +{city_count - 3} more"
        )
        print(f"{rank:2}. [{job['score']:.4f}] {job['title']} @ {job['company']}")
        print(f"    {job['match_tier']} | {loc_display} | {sal}")
        print(f"    {job['url']}\n")
