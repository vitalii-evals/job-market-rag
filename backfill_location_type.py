"""One-shot migration: add jobs.location_type and backfill from raw_json.
Re-parses schema.org jobLocationType (TELECOMMUTE -> remote), the field the
Phase-1 adapter dropped. No re-scrape: raw_json is the re-parse insurance.
Idempotent: safe to rerun."""
import json
import sqlite3


def extract_location_type(raw_json: str) -> str | None:
    """Map schema.org jobLocationType to 'remote' | 'onsite' | None.
    TELECOMMUTE -> remote; anything else present -> onsite; missing -> None."""
    try:
        blob = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    jlt = blob.get("jobLocationType")
    if jlt == "TELECOMMUTE":
        return "remote"
    if blob.get("jobLocation"):   # has a physical location, not flagged remote
        return "onsite"
    return None                    # no signal either way


def main(db_path: str = "jobs.db") -> None:
    conn = sqlite3.connect(db_path)

    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN location_type TEXT")
        print("added column location_type")
    except sqlite3.OperationalError as e:
        print(f"column exists, continuing: {e}")

    rows = conn.execute(
        "SELECT id, raw_json FROM jobs WHERE raw_json IS NOT NULL"
    ).fetchall()

    updates = [(extract_location_type(raw), jid) for jid, raw in rows]
    conn.executemany(
        "UPDATE jobs SET location_type = ? WHERE id = ?", updates
    )
    conn.commit()

    print("\nlocation_type distribution:")
    for lt, n in conn.execute(
        "SELECT location_type, COUNT(*) FROM jobs GROUP BY location_type ORDER BY COUNT(*) DESC"
    ):
        print(f"  {str(lt):8} {n}")

    # cross-check: how many remote-flagged also say 'remote' in the string?
    both = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE location_type='remote' AND LOWER(locations) LIKE '%remote%'"
    ).fetchone()[0]
    remote_total = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE location_type='remote'"
    ).fetchone()[0]
    print(f"\nremote by flag: {remote_total} | of which also say 'remote' in string: {both}")
    print("(the gap = remote jobs string-matching alone would have MISSED)")

    conn.close()


if __name__ == "__main__":
    main()
