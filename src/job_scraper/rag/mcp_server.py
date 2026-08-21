"""MCP server exposing the job-market pipeline as tools for AI clients.

An adapter, not a reimplementation: every tool calls the same functions the
FastAPI endpoints call (ask_graph, top_skills, skill_growth_by_week). One
implementation, two doors — HTTP for programs, MCP for AI clients.

Deliberately hand-written rather than auto-generated from the FastAPI app.
FastMCP can inspect a FastAPI app and turn each route into a tool, but the
descriptions would then be route docstrings written for developers reading
/docs. Tool descriptions ARE the interface here — they're what the model
reasons over when deciding which tool to call — so they're worth writing
deliberately.

Transport: stdio (the default). The client spawns this process; since the
code and jobs.db live on the VPS, the client's command is an ssh wrapper
that runs this remotely and pipes stdio over the connection.
"""
from fastmcp import FastMCP

from job_scraper.rag.graph import ask_graph
from job_scraper.stats.queries import (
    total_jobs_in_scope, top_skills, skill_categories,
    corpus_growth_by_week, skill_growth_by_week,
)

mcp = FastMCP("job-market-rag")


@mcp.tool
def search_jobs(question: str, k: int = 12) -> dict:
    """Ask a natural-language question about the Polish AI/automation job
    market and get an answer grounded in real listings scraped daily from
    JustJoin.it.

    Handles both specific questions ("what LangChain roles are hiring in
    Kraków?", "which companies want n8n experience?") and aggregate ones
    ("which skills are most in demand?") — an internal router picks between
    retrieving individual listings and querying computed market statistics.

    Returns the answer plus a routing trace. Check `grade`: a value of
    "insufficient" means the corpus genuinely does not contain roles of the
    kind asked about, and the answer says so rather than stretching loosely
    related listings to fit. Treat that as low confidence.

    Corpus scope: AI/ML/automation-tagged postings only (~22% of all IT
    listings on the source site), Poland-focused, roughly two months of
    history with daily updates.
    """
    state = ask_graph(question, k=k)
    return {
        "answer": state["answer"],
        "route": state.get("route"),
        "grade": state.get("grade"),
        "attempts": state.get("attempts"),
        "rewritten_query": (
            state.get("search_query")
            if state.get("search_query") != question else None
        ),
    }


@mcp.tool
def market_stats(top_n: int = 15) -> dict:
    """Get computed statistics across the entire AI/automation job corpus:
    which technologies appear most often in postings, how those cluster by
    category, and how many new jobs are discovered each week.

    These are exact counts over every in-scope posting, not a sample — use
    this rather than search_jobs when the question is about the market as a
    whole ("what should I learn?", "how big is this market?", "is it
    growing?").

    Skill counts are presence-per-posting: a job mentioning Python five
    times counts once. Weekly growth is bucketed by discovery date and
    flags the current in-progress week, which is always partial.
    """
    weeks, bootstrap = corpus_growth_by_week()
    return {
        "total_jobs_in_scope": total_jobs_in_scope(),
        "top_skills": [{"skill": s, "postings": c} for s, c in top_skills(top_n)],
        "by_category": [{"category": c, "postings": n} for c, n in skill_categories()],
        "weekly_discovery": [
            {"week_starting": w, "jobs": c, "week_complete": complete}
            for w, c, complete in weeks
        ],
        "excluded_bootstrap_day": bootstrap,
        "note": (
            "Counts cover AI/ML/automation-tagged postings with a detectable "
            "tech stack. The excluded bootstrap day was a one-time bulk "
            "discovery sweep when scraping began, not organic growth."
        ),
    }


@mcp.tool
def skill_trends(min_count: int = 5) -> dict:
    """Compare technology demand between the two most recent complete weeks
    to see what is gaining or losing ground.

    Use this for questions about momentum and direction ("what's rising?",
    "is X still in demand?") rather than absolute popularity — market_stats
    answers the latter.

    min_count filters out skills too rare in either week to support a
    meaningful percentage: going from 1 posting to 11 reads as +1000% but is
    noise. Lower it to see the long tail, accepting that volatility.
    """
    movers, bootstrap = skill_growth_by_week(min_count=min_count)
    return {
        "movers": [
            {
                "skill": s,
                "previous_week": p,
                "latest_week": l,
                "pct_change": round(pct, 1) if pct is not None else None,
                "is_new": pct is None,
            }
            for s, p, l, pct in movers
        ],
        "excluded_bootstrap_day": bootstrap,
        "note": (
            "Compares complete weeks only — the current in-progress week is "
            "excluded, since comparing a partial week against a full one "
            "understates growth and exaggerates decline."
        ),
    }


if __name__ == "__main__":
    mcp.run()
