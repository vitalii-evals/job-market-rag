
import sqlite3
from pathlib import Path

# Resolve the DB path relative to THIS file, not the current working directory.
# store.py is at: src/job_scraper/store.py
# .parent (job_scraper) .parent (src) .parent (project root) → jobs.db lives at root.
# This makes the path stable no matter where cron/you invoke the script from.
DB_PATH = Path(__file__).resolve().parent.parent.parent / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,   -- "source:native_id", e.g. "bulldogjob:238544"
    source          TEXT NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT,
    description     TEXT,
    locations       TEXT,
    employment_type TEXT,
    skills          TEXT,
    salary_min      INTEGER,
    salary_max      INTEGER,
    currency        TEXT,
    salary_period   TEXT,               -- HOUR/DAY/WEEK/MONTH/YEAR — units for salary_min/max
    posted_date     TEXT,
    valid_through   TEXT,
    url             TEXT,
    raw_json        TEXT,
    match_tier      TEXT,               -- 'core' | 'adjacent' — why fetched
    first_seen      TEXT DEFAULT CURRENT_TIMESTAMP,  -- set once by the DEFAULT
    last_seen       TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row      # rows accessible by column name: row["title"]
    conn.execute(SCHEMA)                # idempotent — safe on every run
    conn.commit()
    return conn

UPSERT = """
INSERT INTO jobs (
    id, source, title, company, description, locations,
    employment_type, skills, salary_min, salary_max, currency, salary_period,
    posted_date, valid_through, url, raw_json, match_tier, last_seen
) VALUES (
    :id, :source, :title, :company, :description, :locations,
    :employment_type, :skills, :salary_min, :salary_max, :currency, :salary_period,
    :posted_date, :valid_through, :url, :raw_json, :match_tier, CURRENT_TIMESTAMP
)
ON CONFLICT(id) DO UPDATE SET
    title           = excluded.title,
    company         = excluded.company,
    description     = excluded.description,
    locations       = excluded.locations,
    employment_type = excluded.employment_type,
    skills          = excluded.skills,
    salary_min      = excluded.salary_min,
    salary_max      = excluded.salary_max,
    currency        = excluded.currency,
    salary_period   = excluded.salary_period,
    valid_through   = excluded.valid_through,
    url             = excluded.url,
    raw_json        = excluded.raw_json,
    match_tier      = excluded.match_tier,
    last_seen       = CURRENT_TIMESTAMP;
"""


def upsert_jobs(conn: sqlite3.Connection, jobs: list[dict]) -> None:
    conn.executemany(UPSERT, jobs)
    conn.commit()
