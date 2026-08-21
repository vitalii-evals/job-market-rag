"""Private FastAPI service for the job-market RAG.

Migrated from Flask (see git history: rag/web.py). Flask served three
routes fine, but FastAPI adds what the API surface actually needed:
Pydantic request/response validation, and a self-documenting OpenAPI
schema at /docs — useful when the same pipeline is also exposed via an
MCP server, since both doors then describe the same typed contract.

Still private by design: binds to 127.0.0.1, reached via SSH tunnel.
COMPLIANCE.md restricts raw listing content to private use, and /ask
returns generated answers citing real listings.

Concurrency note: ask() is synchronous (blocking Anthropic SDK call +
numpy retrieval). The /ask route is deliberately a plain `def`, NOT
`async def` — FastAPI runs sync routes in a threadpool, so the event
loop stays free. An `async def` wrapping a blocking call would stall
the whole loop for the duration of every request.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from job_scraper.rag.answer import ask, DEFAULT_K
from job_scraper.rag.dashboard import render_dashboard
from job_scraper.rag.web import INDEX_HTML
from job_scraper.stats.queries import (
    total_jobs_in_scope, top_skills, skill_categories,
    corpus_growth_by_week, skill_growth_by_week,
)

app = FastAPI(
    title="Job Market RAG",
    description="Grounded Q&A and market statistics over live JustJoin listings.",
    version="0.1.0",
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, description="Natural-language question about the job market.")
    k: int = Field(default=DEFAULT_K, ge=1, le=50, description="How many listings to retrieve as grounding context.")


class AskResponse(BaseModel):
    answer: str
    k: int


class StatsResponse(BaseModel):
    total_jobs: int
    top_skills: list[tuple[str, int]]
    categories: list[tuple[str, int]]
    weekly_growth: list[tuple[str, int, bool]]
    bootstrap_day_excluded: str | None


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return INDEX_HTML


@app.get("/stats", response_class=HTMLResponse, include_in_schema=False)
def stats_page() -> str:
    return render_dashboard()


@app.post("/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest) -> AskResponse:
    """Grounded answer over retrieved listings. Sync by design — see
    module docstring on the threadpool/event-loop tradeoff."""
    try:
        return AskResponse(answer=ask(req.question, k=req.k), k=req.k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/api/stats", response_model=StatsResponse)
def stats_api() -> StatsResponse:
    """Machine-readable market stats — same data the /stats dashboard
    renders, exposed as JSON for programmatic use (and, later, as the
    payload behind an MCP tool)."""
    weeks, bootstrap = corpus_growth_by_week()
    return StatsResponse(
        total_jobs=total_jobs_in_scope(),
        top_skills=top_skills(10),
        categories=skill_categories(),
        weekly_growth=weeks,
        bootstrap_day_excluded=bootstrap,
    )


@app.get("/api/skill-growth")
def skill_growth_api(min_count: int = 5):
    """Week-over-week skill movement between the two most recent COMPLETE
    weeks. min_count guards against meaningless percentages off tiny
    samples (a 1 -> 11 jump reads as +1000% but isn't signal)."""
    movers, bootstrap = skill_growth_by_week(min_count=min_count)
    return {
        "movers": [
            {"skill": s, "previous": p, "latest": l, "pct_change": pct}
            for s, p, l, pct in movers
        ],
        "bootstrap_day_excluded": bootstrap,
    }


if __name__ == "__main__":
    import uvicorn

    # 127.0.0.1 ONLY — private. Do NOT change to 0.0.0.0 without auth +
    # compliance review (same constraint the Flask version carried).
    uvicorn.run(app, host="127.0.0.1", port=8000)
