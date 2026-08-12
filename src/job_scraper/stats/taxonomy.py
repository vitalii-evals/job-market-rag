"""General tech-skill taxonomy for market-wide stats — deliberately independent
of match_cv.py's SKILL_VOCAB, which is personal/CV-fit-weighted (n8n weighted 3x
because it's YOUR proven interview lane, not a market-demand signal). This
taxonomy answers "what does the market want", not "how do I compare" — no
weights, just presence/absence, broad unbiased coverage.

v1 — a reasonable starting set, not exhaustive. Same refinement discipline as
match_cv.py's vocabulary: ship it, correct false-positives/negatives found in
real data, don't try to perfect it upfront. Free to re-backfill any time this
changes — extraction is a pure re-parse of already-stored description/title,
no network calls, unlike experience_level's live-fetch backfill.
"""
import re

# term -> category. Term is the literal string stored in jobs.skills
# (comma-joined); category is derived at query time by reversing this dict,
# never stored redundantly — re-categorizing never needs a re-backfill.
TAXONOMY: dict[str, str] = {
    # Languages
    "python": "Languages", "javascript": "Languages", "typescript": "Languages",
    "java": "Languages", "c#": "Languages", "golang": "Languages", "go": "Languages",
    "php": "Languages", "ruby": "Languages", "kotlin": "Languages", "swift": "Languages",
    "rust": "Languages", "scala": "Languages", "sql": "Languages",

    # AI/ML core
    "machine learning": "AI/ML Core", "deep learning": "AI/ML Core",
    "nlp": "AI/ML Core", "computer vision": "AI/ML Core",
    "pytorch": "AI/ML Core", "tensorflow": "AI/ML Core", "keras": "AI/ML Core",
    "scikit-learn": "AI/ML Core", "hugging face": "AI/ML Core",

    # LLM / GenAI
    "llm": "LLM/GenAI", "gpt": "LLM/GenAI", "claude": "LLM/GenAI",
    "gemini": "LLM/GenAI", "mistral": "LLM/GenAI", "llama": "LLM/GenAI",
    "prompt engineering": "LLM/GenAI", "fine-tuning": "LLM/GenAI",
    "rag": "LLM/GenAI", "retrieval-augmented": "LLM/GenAI",

    # Agent / automation frameworks
    "langchain": "Agent/Automation", "langgraph": "Agent/Automation",
    "llamaindex": "Agent/Automation", "autogen": "Agent/Automation",
    "crewai": "Agent/Automation", "haystack": "Agent/Automation",
    "n8n": "Agent/Automation", "zapier": "Agent/Automation",
    "make.com": "Agent/Automation", "rpa": "Agent/Automation",
    "uipath": "Agent/Automation",

    # Vector / embeddings
    "embeddings": "Vector/Embeddings", "vector database": "Vector/Embeddings",
    "pinecone": "Vector/Embeddings", "weaviate": "Vector/Embeddings",
    "milvus": "Vector/Embeddings", "chroma": "Vector/Embeddings",
    "faiss": "Vector/Embeddings",

    # Cloud
    "aws": "Cloud", "azure": "Cloud", "gcp": "Cloud", "google cloud": "Cloud",

    # Data / infra
    "docker": "Data/Infra", "kubernetes": "Data/Infra", "airflow": "Data/Infra",
    "kafka": "Data/Infra", "spark": "Data/Infra", "terraform": "Data/Infra",

    # Databases
    "postgresql": "Databases", "mysql": "Databases", "mongodb": "Databases",
    "redis": "Databases", "elasticsearch": "Databases",

    # Frontend / full-stack
    "react": "Frontend/Full-stack", "vue": "Frontend/Full-stack",
    "angular": "Frontend/Full-stack", "next.js": "Frontend/Full-stack",
    "node.js": "Frontend/Full-stack", "fastapi": "Frontend/Full-stack",
    "django": "Frontend/Full-stack", "flask": "Frontend/Full-stack",

    # MLOps
    "mlflow": "MLOps", "kubeflow": "MLOps", "mlops": "MLOps",
}


def _pattern_for(term: str) -> re.Pattern:
    """Word-boundary on each side, but ONLY where the term's edge is itself
    a word character. Naive \\b on both sides breaks for terms ending in
    punctuation — e.g. 'c#' followed by a space is a non-word -> non-word
    transition, so \\bc#\\b would never match "C# developer" at all. This
    checks each edge independently instead of assuming both sides are safe."""
    escaped = re.escape(term)
    prefix = r"\b" if term[0].isalnum() else ""
    suffix = r"\b" if term[-1].isalnum() else ""
    return re.compile(prefix + escaped + suffix, re.IGNORECASE)


_PATTERNS = {term: _pattern_for(term) for term in TAXONOMY}

# HTML block-tag stripping during JSON-LD extraction sometimes glues two
# words together with no space (e.g. "...roleaTwój..." from a stripped
# </li> or similar) — this silently breaks \b-bounded regex matching,
# since there's no longer a word/non-word transition at the join point.
# Measured impact 2026-08-12: 677 skill matches across 1786 core jobs were
# being lost before this fix, concentrated in java (+126), sql (+112),
# llama (+76), python (+51). Insert a space at every lowercase->uppercase
# transition before matching. Flagged as an open item since 2026-07-29
# ("needs whitespace repair before embedding") but never actually applied
# until now — this fixes it for skill extraction specifically; the raw
# stored description text and its embeddings are unaffected by this
# change and remain a separate, unaddressed issue (see NOTES.md).
_FUSION_RE = re.compile(r'([a-z])([A-Z])')


def _repair_fusion(text: str) -> str:
    return _FUSION_RE.sub(r'\1 \2', text)


def extract_skills(text: str) -> list[str]:
    """Return every taxonomy term found in text (title+description), as the
    literal term strings — not categories. Deterministic substring/regex
    match, same technique as _classify_slug and match_cv's _skill_overlap,
    applied to a new problem: general market signal instead of personal fit
    or discovery filtering.

    Matches against BOTH raw and fusion-repaired text, unioning the results
    — NOT repaired-only. Repaired-only was tried first and caused a real
    regression (caught 2026-08-12): _repair_fusion can't distinguish a
    genuine HTML-stripping artifact ("PythonDeveloper", no space, needs
    repair) from an intentional camelCase brand name ("LangChain",
    "PostgreSQL", "MongoDB", "AutoGen" — same lowercase->uppercase
    signature by design, not a bug). Splitting real brand names apart
    destroyed their compound-term matches (Agent/Automation category
    dropped 339->98, Databases 188->63) even as fusion-artifact recovery
    correctly gained ~677 matches elsewhere. Raw text already matches
    proper camelCase names fine on its own (\b + IGNORECASE don't care
    about internal capitalization) — repaired text ADDS the fusion-bug
    recoveries on top, via union, without being allowed to subtract
    anything the raw pass already found correctly."""
    if not text:
        return []
    repaired = _repair_fusion(text)
    return [
        term for term, pattern in _PATTERNS.items()
        if pattern.search(text) or pattern.search(repaired)
    ]
