import argparse

from job_scraper.rag.embed import embed_pending
from job_scraper.store import get_connection, upsert_jobs
from job_scraper.adapters.justjoin import scrape


def run(limit: int | None, delay: float, embed: bool = True) -> None:
    """Phase-1 pipeline: scrape JustJoin -> upsert into SQLite.
    Phase-2 step: embed any rows still missing a vector (idempotent)."""
    print(f"Scraping JustJoin (limit={limit}, delay={delay}s)...")
    jobs = scrape(limit=limit, delay=delay)
    print(f"Scraped {len(jobs)} jobs. Writing to DB...")
    conn = get_connection()
    upsert_jobs(conn, jobs)
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()
    print(f"Done. {len(jobs)} upserted; {total} rows total in DB.")

    if embed:
        print("Embedding new jobs (WHERE embedding IS NULL)...")
        embedded = embed_pending()
        print(f"Embedding step complete; {embedded} new vectors written.")
    else:
        print("Skipping embed step (--no-embed).")



def main() -> None:
    parser = argparse.ArgumentParser(description="Job-scraper pipeline")
    parser.add_argument("--limit", type=int, default=None,
                        help="max matched jobs (default: no limit — full scan)")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="seconds between page fetches (default 0.5)")
    parser.add_argument("--no-embed", action="store_true",
                        help="skip the post-scrape embedding step")
    args = parser.parse_args()
    run(limit=args.limit, delay=args.delay, embed=not args.no_embed)

if __name__ == "__main__":
    main()
