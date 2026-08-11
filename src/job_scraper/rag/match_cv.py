"""CV-matching: rank all embedded jobs by similarity to the CV.
Reuses retrieve.py's vector store + cosine; the CV is just a (long) query."""
import sys

import docx
import numpy as np

from job_scraper.rag.retrieve import load_vector_store, embed_query
from job_scraper.rag.answer import _format_salary
from datetime import datetime, timedelta, timezone

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

def _within_days(job, days: int | None) -> bool:
    """Keep if posted_date is within the last `days`. None = no date filter.
    posted_date is ISO with trailing Z (JustJoin refresh timestamp)."""
    if days is None:
        return True
    pd = job.get("posted_date")
    if not pd:
        return False
    try:
        dt = datetime.fromisoformat(pd.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return dt >= cutoff

def _detect_seniority(job) -> str:
    """Classify seniority from the title. Deterministic keyword match —
    postings state it almost explicitly, no reasoning required."""
    title = (job.get("title") or "").lower()
    if any(m in title for m in ("senior", "sr.", "lead", "principal", "staff", "head of")):
        return "senior"
    if any(m in title for m in ("junior", "jr.", "graduate", "intern", "entry")):
        return "junior"
    return "mid"  # regular/mid/unspecified — the default, most common bucket

# Weight reflects how proven/strong the skill actually is, not a guess:
# 3 = interview-validated (Comarch interview: n8n+LLM automation, positive
# feedback through 2 rounds) — this IS the strongest real signal you have.
# 2 = proven via NovaDent, or actively defended via job-market-rag.
# 1 = supporting/peripheral — real, but not the differentiator.
SKILL_VOCAB = {
    "Agentic/Automation": (3, ["n8n", "ai agent", "agentic", "workflow automation",
                                "automatyzacj", "no-code", "low-code", "no code", "low code"]),
    "LLM": (2, ["llm", "large language model"]),
    "Anthropic/Claude": (2, ["anthropic", "claude"]),
    "Prompt engineering": (2, ["prompt engineering", "system prompt"]),
    "RAG": (2, ["rag", "retrieval-augmented", "retrieval augmented"]),
    "Embeddings/Vector search": (2, ["embedding", "vector search", "vector database", "semantic search"]),
    "Python": (1, ["python"]),
    "SQL": (1, ["sql", "postgresql", "postgres"]),
    "Web scraping/APIs": (1, ["web scraping", "rest api", "api integration", "webhook"]),
    "Linux/Infra": (1, ["linux", "vps", "ssh", "docker"]),
    "Git": (1, ["git"]),
}
MAX_SKILL_SCORE = sum(w for w, _ in SKILL_VOCAB.values())  # 18
# Blend weights: cosine (broad semantic direction) + skill-overlap (your
# proven-strength categories). Tunable — adjust and re-run to see effect.
COSINE_WEIGHT = 0.6
SKILL_WEIGHT = 0.4

def _skill_overlap(job) -> tuple[int, int, list[str]]:
    """Weighted skill-category match. A proven-strength category (n8n/
    automation) counts more than a peripheral one (Git), so a job matching
    your strongest, interview-tested lane outranks one matching only minor
    overlaps. Deterministic substring match — transparent, no API calls."""
    text = f"{job.get('title', '')} {job.get('description', '')}".lower()
    matched = [
        skill for skill, (weight, terms) in SKILL_VOCAB.items()
        if any(term in text for term in terms)
    ]
    score = sum(SKILL_VOCAB[s][0] for s in matched)
    return score, MAX_SKILL_SCORE, matched

OTHER_LANGUAGE_MARKERS = ("java ", "java)", "golang", " go ", "angular", "c#", ".net",
                           "php", "ruby", "kotlin", "swift", "rust", "scala")


def _stack_mismatch(job) -> bool:
    """Flag if the title centers on a non-Python language. Title-only (the
    headline signal, not a passing mention buried in the description) — and
    only if Python isn't also named, since dual-stack roles aren't a mismatch."""
    title = (job.get("title") or "").lower()
    if "python" in title:
        return False
    return any(marker in title for marker in OTHER_LANGUAGE_MARKERS)

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


def rank_jobs(cv_path: str = "cv.docx", top_n: int = 20, days: int | None = None, db_path: str = "jobs.db"):
    """Rank embedded jobs by a BLEND of cosine similarity and weighted skill
    overlap (not cosine alone) — a job matching your proven-strength skills
    (n8n/automation) can outrank a higher-cosine job that's just Python/RAG-
    vocabulary-dense. Then collapse near-identical postings (same title+company
    across cities). Returns top_n DISTINCT jobs, best first."""
    matrix, metadata = load_vector_store(db_path)   # (N, 1024) + aligned meta
    query = build_cv_query(cv_path)
    q = embed_query(query)                            # CV as a query vector
    scores = matrix @ q                              # cosine (vectors are unit-norm)

    # Pass 1: apply hard gates, compute combined score for every survivor.
    candidates = []
    for i in range(len(metadata)):
        job = metadata[i]
        if not _passes_location(job):                # Kraków or remote only
            continue
        if not _within_days(job, days):              # posted within N days
            continue
        seniority = _detect_seniority(job)
        if seniority == "senior":                     # exclude explicit-senior
            continue
        if _stack_mismatch(job):                      # exclude non-Python-core roles
            continue

        cosine = float(scores[i])
        n_match, n_total, matched_skills = _skill_overlap(job)
        skill_fraction = n_match / n_total if n_total else 0.0
        combined = COSINE_WEIGHT * cosine + SKILL_WEIGHT * skill_fraction

        candidates.append({
            **job,
            "score": cosine,
            "combined_score": combined,
            "seniority": seniority,
            "skill_matches": (n_match, n_total, matched_skills),
            "_locs": [(job["locations"] or "").strip()],
        })

    # Pass 2: sort by the blend (NOT raw cosine), then dedupe (title, company).
    candidates.sort(key=lambda e: e["combined_score"], reverse=True)

    seen = {}
    distinct = []
    for entry in candidates:
        key = (entry["title"], entry["company"])
        if key in seen:
            existing = seen[key]
            loc = entry["_locs"][0]
            if loc and loc not in existing["_locs"]:
                existing["_locs"].append(loc)
            continue
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
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    results = rank_jobs(top_n=top_n, days=days)
    print(f"(filtered to jobs posted within {days} days)\n")
    for rank, job in enumerate(results, 1):
        sal = _format_salary(job)
        loc = job["locations"] or "location n/a"
        # if many cities merged, show count compactly
        city_count = loc.count(",") + 1 if loc != "location n/a" else 0
        loc_display = loc if city_count <= 3 else (
            ", ".join(loc.split(", ")[:3]) + f", +{city_count - 3} more"
        )
        sen_tag = {"senior": "[SENIOR]", "junior": "[JUNIOR]", "mid": ""}[job["seniority"]]
        n_match, n_total, matched_skills = job["skill_matches"]
        skills_str = ", ".join(matched_skills) if matched_skills else "none"
        print(f"{rank:2}. [blend {job['combined_score']:.4f} | cos {job['score']:.4f}] {sen_tag} {job['title']} @ {job['company']}")
        print(f"    {job['match_tier']} | {loc_display} | {sal}")
        print(f"    skills: {n_match}/{n_total} ({skills_str})")
        print(f"    {job['url']}\n")
