"""One-shot migration: add jobs.salary_period and backfill from raw_json.
Re-parses schema.org baseSalary.value.unitText — the field the Phase-1
adapter dropped. No re-scrape: raw_json is the re-parse insurance.
Idempotent: safe to rerun (ADD COLUMN guarded; UPDATE overwrites identically)."""
import json
import sqlite3

VALID_UNITS = {"HOUR", "DAY", "WEEK", "MONTH", "YEAR"}


def extract_period(raw_json: str) -> str | None:
    """Pull baseSalary.value.unitText. Returns a VALID_UNITS value or None."""
    try:
        bs = json.loads(raw_json).get("baseSalary")
        if not bs or not isinstance(bs.get("value"), dict):
            return None
        ut = bs["value"].get("unitText")
        return ut if ut in VALID_UNITS else None
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None


def main(db_path: str = "jobs.db") -> None:
    conn = sqlite3.connect(db_path)

    # add column (guarded — rerunnable)
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN salary_period TEXT")
        print("added column salary_period")
    except sqlite3.OperationalError as e:
        print(f"column exists, continuing: {e}")

    # backfill every row that has raw_json
    rows = conn.execute(
        "SELECT id, raw_json FROM jobs WHERE raw_json IS NOT NULL"
    ).fetchall()

    updates = [(extract_period(raw), jid) for jid, raw in rows]
    conn.executemany(
        "UPDATE jobs SET salary_period = ? WHERE id = ?", updates
    )
    conn.commit()

    # verify distribution matches what we saw in raw_json
    print("\nsalary_period distribution after backfill:")
    for period, n in conn.execute(
        "SELECT salary_period, COUNT(*) FROM jobs GROUP BY salary_period ORDER BY COUNT(*) DESC"
    ):
        print(f"  {str(period):8} {n}")

    # sanity: rows WITH a salary but NULL period (should be ~0 — every salaried
    # row should have had a unitText)
    orphans = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE salary_min IS NOT NULL AND salary_period IS NULL"
    ).fetchone()[0]
    print(f"\nsalaried rows missing period (want ~0): {orphans}")

    conn.close()


if __name__ == "__main__":
    main()
