import sys

import anthropic

from job_scraper.rag.retrieve import search

ANSWER_MODEL = "claude-sonnet-5"   # swappable; Opus for harder analysis, Haiku for cheap
DESC_TRUNCATE = 500
DEFAULT_K = 12

SYSTEM_PROMPT = """You are a job-market analyst answering questions about a live corpus of job listings.

Rules:
- Answer ONLY from the JOB LISTINGS provided in the user message. Do not use outside knowledge about the job market.
- If the listings do not contain enough information to answer, say so plainly. Do not invent jobs, salaries, or companies.
- Cite the specific listings that support each claim using their id in brackets, e.g. [justjoin:dcg-...].
- When useful, aggregate: count roles, note salary ranges, spot location or skill patterns across the listings.
- Be concise and factual. This is analysis of real data, not marketing copy."""


def _format_salary(job) -> str:
    lo, hi, cur = job["salary_min"], job["salary_max"], job["currency"] or ""
    if lo is None and hi is None:
        return "not stated"
    lo = lo if lo is not None else "?"
    hi = hi if hi is not None else "?"
    period = job.get("salary_period")
    per = f"/{period.lower()}" if period else ""
    return f"{lo}-{hi} {cur}{per}".strip()

def build_context(jobs) -> str:
    """Render retrieved jobs into a compact grounded context block.
    Descriptions truncated: full text was retrieval fuel; the answer
    layer needs the gist, not every word."""
    blocks = []
    for job in jobs:
        desc = (job["description"] or "").strip()
        if len(desc) > DESC_TRUNCATE:
            desc = desc[:DESC_TRUNCATE].rstrip() + "…"
        blocks.append(
            f"[{job['id']}] {job['title']} @ {job['company']}\n"
            f"Location: {job['locations']} | Type: {job['employment_type']} "
            f"| Salary: {_format_salary(job)} | Tier: {job['match_tier']} "
            f"| Relevance: {job['score']:.3f}\n"
            f"URL: {job['url']}\n"
            f"Description: {desc}"
        )
    return "\n\n".join(blocks)


def ask(question: str, k: int = DEFAULT_K, db_path: str = "jobs.db") -> str:
    """One-shot grounded RAG: retrieve top-k jobs, answer strictly from
    them with citations."""
    jobs = search(question, k=k, db_path=db_path)
    context = build_context(jobs)

    user_message = (
        f"JOB LISTINGS (top {len(jobs)} by relevance to the question):\n\n"
        f"{context}\n\n"
        f"---\n\nQUESTION: {question}"
    )

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    response = client.messages.create(
        model=ANSWER_MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(b.text for b in response.content if b.type == "text")


if __name__ == "__main__":
    question = (
        sys.argv[1] if len(sys.argv) > 1
        else "What senior AI/LLM engineering roles are available, and where are they located?"
    )
    print(f"Q: {question}\n")
    print(ask(question))
