"""LangChain BaseRetriever wrapping the hand-built numpy vector store.

The retrieval implementation does NOT change — this is an interface, not a
replacement. load_vector_store + embed_query + a single matvec still do the
actual work (see retrieve.py). What the wrapper buys: the graph depends on
the standard Retriever contract rather than on this project's specific
search() signature, so the vector store could later be swapped (FAISS,
pgvector, whatever) without touching any node that consumes it.

Deliberately NOT using a LangChain vector-store integration here. Those
would replace the hand-built retrieval that's the core interview claim of
this project. Standard interface, custom implementation — the framework
sits on top of owned code, not in place of it.
"""
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from job_scraper.rag.retrieve import search

# Fields carried into Document.metadata. Everything the answer layer or a
# citation needs — page_content holds the text the LLM reads, metadata
# holds what it cites and filters on.
_METADATA_FIELDS = (
    "id", "title", "company", "locations", "url", "match_tier",
    "salary_min", "salary_max", "currency", "salary_period",
    "location_type", "experience_level", "posted_date", "employment_type",
    "skills", "score",
)


class JobRetriever(BaseRetriever):
    """Retrieves job listings by cosine similarity to the query."""

    k: int = 12
    db_path: str = "jobs.db"

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        jobs = search(query, k=self.k, db_path=self.db_path)
        return [self._to_document(job) for job in jobs]

    @staticmethod
    def _to_document(job: dict[str, Any]) -> Document:
        """Job dict -> Document. page_content is title+company+description
        because that's what the model should reason over; structured fields
        stay in metadata so they can be used for citation and filtering
        without being buried in prose."""
        content = (
            f"{job.get('title')} @ {job.get('company')}\n"
            f"{job.get('description') or ''}"
        )
        metadata = {f: job.get(f) for f in _METADATA_FIELDS}
        return Document(page_content=content, metadata=metadata)
