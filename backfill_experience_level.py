"""One-time backfill: experience_level wasn't captured by the original adapter
(not in JSON-LD, unlike salary_period/location_type) — has to be re-fetched live,
not re-parsed from raw_json. Expired listings 404 and stay NULL permanently;
that's fine, freshness gates already exclude them from matching.
Kept in repo for provenance, not rerun after this pass.
"""
import time
import httpx

from job_scraper.adapters.justjoin import _get, _parse_experience_level
from job_scraper.store import get_connection

DELAY = 0.5

def main() -> None:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, url FROM jobs "
        "WHERE source = 'justjoin' AND experience_level IS NULL AND url IS NOT NULL"
    ).fetchall()
    print(f"{len(rows)} rows to backfill")

    updated = skipped = failed = 0
    with httpx.Client() as client:
        for i, row in enumerate(rows, 1):
            job_id, url = row["id"], row["url"]
            try:
                page_bytes = _get(client, url)
            except httpx.HTTPError as e:
                print(f"  [{i}/{len(rows)}] FETCH FAILED (likely expired) {job_id}: {e}")
                failed += 1
                time.sleep(DELAY)
                continue

            level = _parse_experience_level(page_bytes)
            if level is None:
                print(f"  [{i}/{len(rows)}] no match: {job_id}")
                skipped += 1
            else:
                conn.execute("UPDATE jobs SET experience_level = ? WHERE id = ?", (level, job_id))
                conn.commit()
                print(f"  [{i}/{len(rows)}] {job_id} -> {level}")
                updated += 1
            time.sleep(DELAY)

    print(f"\nDone. updated={updated} skipped={skipped} failed(expired/error)={failed}")

if __name__ == "__main__":
    main()
