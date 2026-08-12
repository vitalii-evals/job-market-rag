"""One-time (but freely re-runnable) backfill: populate the skills column,
which has existed in the schema since Phase 1 but was always NULL — JustJoin's
JSON-LD never carried it. Unlike experience_level, needs NO network calls:
description/title are already stored, so this is a pure local re-parse, same
shape as salary_period/location_type. Safe to re-run any time taxonomy.py
changes — nothing here is a one-way door like the experience_level backfill
(no expired-listing loss risk, since nothing needs re-fetching)."""
from job_scraper.stats.taxonomy import extract_skills
from job_scraper.store import get_connection


def main() -> None:
    conn = get_connection()
    rows = conn.execute("SELECT id, title, description FROM jobs").fetchall()
    print(f"{len(rows)} rows to process")

    updated = 0
    for row in rows:
        text = f"{row['title'] or ''} {row['description'] or ''}"
        skills = extract_skills(text)
        skills_str = ", ".join(sorted(skills)) if skills else None
        conn.execute("UPDATE jobs SET skills = ? WHERE id = ?", (skills_str, row["id"]))
        updated += 1

    conn.commit()
    print(f"done. updated={updated}")


if __name__ == "__main__":
    main()
