import argparse

from job_scraper.store import get_connection, upsert_jobs
from job_scraper.adapters.justjoin import scrape


def run(limit: int | None, delay: float) -> None:
    """Phase-1 pipeline: scrape JustJoin -> upsert into SQLite."""
    print(f"Scraping JustJoin (limit={limit}, delay={delay}s)...")
    jobs = scrape(limit=limit, delay=delay)
    print(f"Scraped {len(jobs)} jobs. Writing to DB...")

    conn = get_connection()
    upsert_jobs(conn, jobs)
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()

    print(f"Done. {len(jobs)} upserted; {total} rows total in DB.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Job-scraper pipeline")
    parser.add_argument("--limit", type=int, default=None,
                        help="max matched jobs (default: no limit — full scan)")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="seconds between page fetches (default 0.5)")
    args = parser.parse_args()
    run(limit=args.limit, delay=args.delay)


if __name__ == "__main__":
    main()
