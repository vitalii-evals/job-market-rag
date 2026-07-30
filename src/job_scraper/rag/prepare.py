
import html
import re


def clean_text(text: str) -> str:
    """Normalize whitespace only. Does NOT attempt to un-fuse block-boundary
    words (e.g. 'DeveloperaTwój') — splitting camelCase would corrupt tech
    tokens like 'PostgreSQL'/'PyTorch', which are the retrieval signal."""
    text = html.unescape(text)        # idempotent insurance for stray &amp; etc.
    text = re.sub(r"\s+", " ", text)  # \s matches \xa0 and unicode ws in str mode
    return text.strip()


def compose_embed_text(row) -> str:
    """Build one embed string per job. Structured fields first (they anchor
    filtered queries like 'remote senior >20k PLN'), prose last. Null/empty
    fields are OMITTED so the vector isn't polluted with 'None' noise.
    `row` is a sqlite3.Row or dict with the queried columns."""
    parts = []

    title = (row["title"] or "").strip()
    company = (row["company"] or "").strip()
    if title and company:
        parts.append(f"{title} at {company}.")
    elif title:
        parts.append(f"{title}.")

    locations = (row["locations"] or "").strip()
    if locations:
        parts.append(f"Location: {locations}.")

    emp = (row["employment_type"] or "").strip()
    if emp:
        parts.append(f"Employment: {emp}.")

    skills = (row["skills"] or "").strip()
    if skills:
        parts.append(f"Skills: {skills}.")

    smin, smax = row["salary_min"], row["salary_max"]
    cur = (row["currency"] or "").strip()
    if smin or smax:
        lo = smin if smin is not None else "?"
        hi = smax if smax is not None else "?"
        parts.append(f"Salary: {lo}-{hi} {cur}".strip() + ".")

    desc = clean_text(row["description"] or "")
    if desc:
        parts.append(desc)

    return "\n".join(parts)
