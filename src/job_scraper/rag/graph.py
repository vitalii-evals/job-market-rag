"""LangGraph agent for job-market Q&A.

WHY A GRAPH AND NOT THE LINEAR PIPELINE (answer.py):
answer.py is unconditionally embed -> retrieve top-k -> generate. That is
correct for "what roles match X" but WRONG for aggregate questions. Ask
"which skills are growing fastest?" and the linear path samples 12 listings
and reasons over them, when stats/queries.py already computes the real
answer across all 1,700 in-scope jobs. The model then answers confidently
from a 0.7% sample — fluent and wrong, the worst failure mode.

The graph routes instead: classify the question, then either query the
structured aggregates or retrieve listings. Two genuinely different data
paths for two genuinely different question types — a conditional edge is
the honest expression of that, not decoration over a linear flow.

answer.py is deliberately KEPT, not replaced. It's the hand-built raw-SDK
implementation this project's principles are built on; the graph sits
alongside it as the framework-based path. Both remain runnable, which is
what makes "I built it by hand, then migrated to LangGraph" verifiable
rather than a retroactive story.
"""
from typing import Literal, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from job_scraper.rag.retriever import JobRetriever
from job_scraper.stats.queries import (
    total_jobs_in_scope, top_skills, skill_categories,
    corpus_growth_by_week, skill_growth_by_week,
)

ROUTER_MODEL = "claude-haiku-4-5-20251001"   # cheap + fast; classification is easy
ANSWER_MODEL = "claude-sonnet-5"             # matches answer.py
DESC_TRUNCATE = 500
MAX_ATTEMPTS = 2   # initial retrieval + at most one rewrite-and-retry


class GraphState(TypedDict, total=False):
    """State threaded through every node. total=False because nodes fill
    different keys — the router sets `route`, only one branch sets `docs`
    or `stats_context`.

    The retry fields are what make this a graph rather than a chain:
    `attempts` is the termination guard, `search_query` diverges from
    `question` after a rewrite (the user's question never changes; what we
    search for does), and `grade` carries the loop decision between nodes."""
    question: str
    k: int
    route: Literal["stats", "listings"]
    docs: list[Document]
    stats_context: str
    answer: str
    search_query: str
    grade: Literal["good", "rewrite", "insufficient"]
    attempts: int


ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Classify a question about a job-market database into exactly one route.\n\n"
     "'stats' — aggregate questions about the market as a whole: counts, "
     "trends over time, which skills are most in demand, growth rates, "
     "category breakdowns. These need computed totals across the entire "
     "corpus.\n\n"
     "'listings' — questions about specific jobs: what roles exist, who is "
     "hiring, salaries for particular positions, requirements of individual "
     "postings. These need the actual listings retrieved.\n\n"
     "Answer with exactly one word: stats or listings."),
    ("human", "{question}"),
])

ANSWER_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a job-market analyst answering questions about a live corpus "
     "of job listings.\n"
     "Rules:\n"
     "- Answer ONLY from the data provided in the user message. Do not use "
     "outside knowledge about the job market.\n"
     "- If the data does not contain enough information to answer, say so "
     "plainly. Do not invent jobs, salaries, or companies.\n"
     "- When listings are provided, cite each as a clickable markdown link "
     "using its title and url.\n"
     "- When statistics are provided, these are computed over the ENTIRE "
     "in-scope corpus, not a sample — state figures directly.\n"
     "- Be concise and factual. This is analysis of real data, not "
     "marketing copy."),
    ("human", "{context}\n\n---\n\nQUESTION: {question}"),
])


GRADER_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You judge whether retrieved job listings can answer a question.\n\n"
     "Reply with exactly one word:\n\n"
     "'good' — the listings contain enough relevant material to answer, "
     "even partially. A small number of genuinely on-topic listings counts "
     "as good.\n\n"
     "'rewrite' — the listings are off-topic in a way that suggests the "
     "SEARCH QUERY was poorly phrased: too vague, wrong vocabulary, or "
     "phrased as a question rather than as the text of a matching job "
     "posting. A better query would plausibly find better listings.\n\n"
     "'insufficient' — the query looks reasonable and the corpus simply "
     "does not contain this kind of role. Rewording would not help.\n\n"
     "The distinction between 'rewrite' and 'insufficient' matters: one "
     "means try again, the other means answer honestly that the data "
     "isn't there."),
    ("human",
     "QUESTION: {question}\n\nSEARCH QUERY USED: {search_query}\n\n"
     "RETRIEVED LISTINGS:\n{summaries}"),
])

REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Rewrite a job-search question into a short search query that will "
     "match the TEXT OF A JOB POSTING via semantic similarity.\n\n"
     "Vectors match documents that look like the query, so phrase it as a "
     "job posting would read — role title plus key technologies — not as a "
     "question. Use standard industry vocabulary.\n\n"
     "Example: 'are there any jobs where I would build chatbots?' becomes "
     "'conversational AI engineer chatbot LLM development'.\n\n"
     "Output only the rewritten query, nothing else."),
    ("human", "{question}"),
])


def route_question(state: GraphState) -> GraphState:
    """Classify the question. One cheap Haiku call — the whole point is that
    picking a data path shouldn't cost a Sonnet call."""
    llm = ChatAnthropic(model=ROUTER_MODEL, max_tokens=10, temperature=0)
    result = (ROUTER_PROMPT | llm).invoke({"question": state["question"]})
    decision = result.content.strip().lower()
    # Default to listings on anything unexpected: retrieving when we should
    # have aggregated returns a partial answer, while aggregating when we
    # should have retrieved returns something entirely unrelated to the ask.
    return {"route": "stats" if decision.startswith("stats") else "listings"}


def fetch_stats(state: GraphState) -> GraphState:
    """The branch that fixes the bug — real aggregates over the whole
    corpus, not a 12-listing sample."""
    weeks, bootstrap = corpus_growth_by_week()
    movers, _ = skill_growth_by_week()

    lines = [
        f"MARKET STATISTICS (computed over all {total_jobs_in_scope()} "
        f"in-scope AI/automation jobs):",
        "",
        "Top skills by number of postings mentioning them:",
    ]
    lines += [f"  {s}: {c}" for s, c in top_skills(15)]
    lines += ["", "Postings by skill category:"]
    lines += [f"  {c}: {n}" for c, n in skill_categories()]
    lines += ["", "New jobs discovered per week:"]
    lines += [
        f"  {w}: {c}" + ("" if complete else "  (week still in progress)")
        for w, c, complete in weeks
    ]
    if bootstrap:
        lines.append(
            f"  (excludes {bootstrap}: one-time initial discovery sweep, "
            f"not organic growth)"
        )
    if movers:
        lines += ["", "Week-over-week skill movement (two most recent complete weeks):"]
        lines += [
            f"  {s}: {p} -> {l} ({pct:+.0f}%)" if pct is not None else f"  {s}: new ({l})"
            for s, p, l, pct in movers[:15]
        ]
    return {"stats_context": "\n".join(lines)}


def retrieve_listings(state: GraphState) -> GraphState:
    """The RAG branch — the existing hand-built retrieval, via the
    LangChain retriever interface. Searches `search_query`, which starts
    equal to the question and diverges after a rewrite."""
    query = state.get("search_query") or state["question"]
    retriever = JobRetriever(k=state.get("k", 12))
    return {
        "docs": retriever.invoke(query),
        "search_query": query,
        "attempts": state.get("attempts", 0) + 1,
    }


def grade_documents(state: GraphState) -> GraphState:
    """Judge the retrieval. Distinguishes a bad query (retry) from a thin
    corpus (stop and say so) — collapsing those two into one verdict would
    make every empty result trigger a pointless rewrite."""
    docs = state.get("docs", [])
    if not docs:
        return {"grade": "insufficient"}

    summaries = "\n".join(
        f"- {d.metadata.get('title')} @ {d.metadata.get('company')} "
        f"(similarity {d.metadata.get('score'):.3f}, "
        f"skills: {d.metadata.get('skills') or 'none detected'})"
        for d in docs
    )
    llm = ChatAnthropic(model=ROUTER_MODEL, max_tokens=10, temperature=0)
    result = (GRADER_PROMPT | llm).invoke({
        "question": state["question"],
        "search_query": state.get("search_query", state["question"]),
        "summaries": summaries,
    })
    verdict = result.content.strip().lower()

    for candidate in ("insufficient", "rewrite", "good"):
        if candidate in verdict:
            return {"grade": candidate}
    # Unrecognized output: proceed rather than loop. Answering from
    # imperfect docs beats burning a retry on a grader malfunction.
    return {"grade": "good"}


def rewrite_query(state: GraphState) -> GraphState:
    """Reformulate into posting-shaped text. The user's `question` is never
    modified — only what we search with."""
    llm = ChatAnthropic(model=ROUTER_MODEL, max_tokens=100, temperature=0)
    result = (REWRITE_PROMPT | llm).invoke({"question": state["question"]})
    return {"search_query": result.content.strip()}


def _format_docs(docs: list[Document]) -> str:
    blocks = []
    for doc in docs:
        m = doc.metadata
        desc = doc.page_content
        if len(desc) > DESC_TRUNCATE:
            desc = desc[:DESC_TRUNCATE].rstrip() + "…"
        salary = (
            f"{m.get('salary_min')}-{m.get('salary_max')} {m.get('currency') or ''}"
            if m.get("salary_min") or m.get("salary_max") else "not stated"
        )
        blocks.append(
            f"[{m.get('id')}] {m.get('title')} @ {m.get('company')}\n"
            f"Location: {m.get('locations')} | Level: {m.get('experience_level')} "
            f"| Salary: {salary} | Relevance: {m.get('score'):.3f}\n"
            f"Skills detected: {m.get('skills') or 'none'}\n"
            f"URL: {m.get('url')}\n"
            f"{desc}"
        )
    return (
        f"JOB LISTINGS (top {len(docs)} by relevance to the question):\n\n"
        + "\n\n".join(blocks)
    )


def generate(state: GraphState) -> GraphState:
    """Single generation node for both branches — the context differs, the
    grounding contract does not."""
    state = {**state, **exhausted_is_insufficient(state)}
    context = state.get("stats_context") or _format_docs(state.get("docs", []))
    if state.get("grade") == "insufficient":
        context += (
            "\n\n[RETRIEVAL NOTE: these listings were judged a poor match "
            "for the question. Say plainly that the corpus does not appear "
            "to contain roles of this kind, then describe what it does "
            "contain that is closest. Do not stretch these listings to fit.]"
        )
    llm = ChatAnthropic(model=ANSWER_MODEL, max_tokens=1500)
    result = (ANSWER_PROMPT | llm).invoke(
        {"context": context, "question": state["question"]}
    )
    # Return the corrected grade too, not just the answer — ask_graph exposes
    # full state so callers (API, MCP server) can detect a low-confidence
    # result. Returning only `answer` left the reported grade stale at
    # "rewrite" even when generation correctly treated it as insufficient.
    out = {"answer": result.content}
    if state.get("grade") == "insufficient":
        out["grade"] = "insufficient"
    return out


def _pick_branch(state: GraphState) -> Literal["stats", "listings"]:
    """Conditional edge function — reads the route the router node set."""
    return state["route"]


def _after_grade(state: GraphState) -> Literal["rewrite", "generate"]:
    """Loop guard. Rewrites only on a 'rewrite' verdict AND only while under
    the attempt cap — without the cap check a stubbornly-bad query would
    cycle indefinitely, since nothing else terminates the loop."""
    if state.get("grade") == "rewrite" and state.get("attempts", 0) < MAX_ATTEMPTS:
        return "rewrite"
    return "generate"


def exhausted_is_insufficient(state: GraphState) -> GraphState:
    """Reclassify a cap-exhausted 'rewrite' as 'insufficient'. If the query
    was already rewritten once and retrieval is STILL judged bad, the
    distinction the grader drew no longer holds: we tried the better query
    and it didn't help, which is the definition of a thin corpus. Without
    this the insufficient branch is unreachable — the grade stays 'rewrite'
    and generate never gets the honesty instruction it was built for."""
    if state.get("grade") == "rewrite" and state.get("attempts", 0) >= MAX_ATTEMPTS:
        return {"grade": "insufficient"}
    return {}


def build_graph():
    """Assemble and compile the graph. Kept as a function rather than a
    module-level constant so importing this module doesn't do work."""
    from langgraph.graph import StateGraph, START, END

    builder = StateGraph(GraphState)
    builder.add_node("route", route_question)
    builder.add_node("stats", fetch_stats)
    builder.add_node("listings", retrieve_listings)
    builder.add_node("grade", grade_documents)
    builder.add_node("rewrite", rewrite_query)
    builder.add_node("generate", generate)

    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route", _pick_branch, {"stats": "stats", "listings": "listings"}
    )
    builder.add_edge("stats", "generate")
    builder.add_edge("listings", "grade")
    builder.add_conditional_edges(
        "grade", _after_grade, {"rewrite": "rewrite", "generate": "generate"}
    )
    builder.add_edge("rewrite", "listings")   # the loop
    builder.add_edge("generate", END)

    return builder.compile()


_GRAPH = None


def ask_graph(question: str, k: int = 12) -> dict:
    """Run the graph. Returns the full final state (not just the answer) so
    callers can inspect which route was taken — visibility the linear
    pipeline never offered."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH.invoke({"question": question, "k": k})


if __name__ == "__main__":
    import sys

    question = (
        " ".join(sys.argv[1:]) if len(sys.argv) > 1
        else "Which skills are growing fastest in AI automation roles?"
    )
    result = ask_graph(question)
    print(f"Q: {question}")
    trace = f"route: {result['route']}"
    if result.get("attempts"):
        trace += f" | attempts: {result['attempts']} | grade: {result.get('grade')}"
    print(f"[{trace}]")
    if result.get("search_query") and result["search_query"] != question:
        print(f"[rewritten query: {result['search_query']}]")
    print()
    print(result["answer"])
