"""Market-wide statistics over the AI/automation job corpus.

Scope, per project decision (2026-08-12): match_tier='core' AND skills IS NOT
NULL. Uses stats/taxonomy.py's independent, unweighted vocabulary (NOT
match_cv.py's personal CV-fit-weighted SKILL_VOCAB).

THREE distortions found and fixed here (2026-08-12):

1. posted_date is right-censored + bootstrap-contaminated for a weekly
   trend (see git history / Notion for full explanation) — kept only as an
   honestly-labeled snapshot distribution, never a trend.
2. first_seen fixes #1 (stamped once, at discovery, final the moment a week
   ends) but needs the single bootstrap sweep day excluded (detected
   dynamically).
3. The CURRENT week is still in-progress and must not be compared as if
   complete — growth comparisons use the two most recent COMPLETE weeks.

A FOURTH bug found and fixed in review, before shipping: an early version
of #2/#3 shared one helper between job-count and skill-count aggregation,
and corpus_growth_by_week summed the skill-keyed Counter instead of
counting jobs — silently inflating weekly totals by ~5-6x (one job with N
tagged skills contributed N to the sum instead of 1). Job-count and
skill-count are now tracked as genuinely separate structures, and _main_
self-checks the accounted total against the known DB count so this class
of error can't silently ship again.
"""
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

STATS_WHERE = "match_tier = 'core' AND skills IS NOT NULL"


def _connect(db_path: str = "jobs.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_posted(pd: str | None) -> datetime | None:
    if not pd:
        return None
    try:
        return datetime.fromisoformat(pd.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _week_start(dt: datetime) -> str:
    monday = dt - timedelta(days=dt.weekday())
    return monday.date().isoformat()


def _current_week_start() -> str:
    return _week_start(datetime.now(timezone.utc))


def _detect_bootstrap_day(daily_counts: Counter) -> str | None:
    if len(daily_counts) < 2:
        return None
    ranked = sorted(daily_counts.items(), key=lambda x: -x[1])
    (_, top_count), (_, second_count) = ranked[0], ranked[1]
    if second_count and top_count > 3 * second_count:
        return ranked[0][0]
    return None


def posted_date_distribution(db_path: str = "jobs.db") -> list[tuple[str, int]]:
    """Snapshot histogram of original posting dates — NOT a weekly trend."""
    conn = _connect(db_path)
    rows = conn.execute(f"SELECT posted_date FROM jobs WHERE {STATS_WHERE}").fetchall()
    conn.close()

    counts: Counter[str] = Counter()
    for row in rows:
        dt = _parse_posted(row["posted_date"])
        if dt:
            counts[_week_start(dt)] += 1
    return sorted(counts.items())


def _weekly_first_seen(rows) -> tuple[Counter, dict[str, Counter], str | None]:
    """Bucket first_seen-based rows by week into TWO SEPARATE structures —
    job counts and skill counts — so summing one can never be mistaken for
    the other. Returns (week_job_counts, week_skill_counts, bootstrap_day)."""
    daily_totals: Counter[str] = Counter()
    for row in rows:
        if row["first_seen"]:
            daily_totals[row["first_seen"][:10]] += 1
    bootstrap_day = _detect_bootstrap_day(daily_totals)

    week_job_counts: Counter[str] = Counter()
    week_skill_counts: dict[str, Counter] = {}
    for row in rows:
        fs = row["first_seen"]
        if not fs or fs[:10] == bootstrap_day:
            continue
        week = _week_start(datetime.fromisoformat(fs[:10]))
        week_job_counts[week] += 1  # one increment per JOB, unambiguous
        bucket = week_skill_counts.setdefault(week, Counter())
        for skill in (row["skills"] or "").split(", "):
            if skill:
                bucket[skill] += 1
    return week_job_counts, week_skill_counts, bootstrap_day


def corpus_growth_by_week(db_path: str = "jobs.db") -> tuple[list[tuple[str, int, bool]], str | None]:
    """Weekly job count by first_seen. Each entry: (week_start, count,
    is_complete)."""
    conn = _connect(db_path)
    rows = conn.execute(f"SELECT first_seen, skills FROM jobs WHERE {STATS_WHERE}").fetchall()
    conn.close()

    week_job_counts, _, bootstrap_day = _weekly_first_seen(rows)
    current = _current_week_start()
    weekly = [
        (week, count, week != current)
        for week, count in sorted(week_job_counts.items())
    ]
    return weekly, bootstrap_day


def total_jobs_in_scope(db_path: str = "jobs.db") -> int:
    """Count of jobs matching STATS_WHERE — the dashboard's headline number
    and the self-check denominator, exposed as a real public function
    rather than reaching into a private helper from another module."""
    conn = _connect(db_path)
    count = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {STATS_WHERE}").fetchone()[0]
    conn.close()
    return count


def top_skills(n: int = 10, db_path: str = "jobs.db") -> list[tuple[str, int]]:
    conn = _connect(db_path)
    rows = conn.execute(f"SELECT skills FROM jobs WHERE {STATS_WHERE}").fetchall()
    conn.close()

    counts: Counter[str] = Counter()
    for row in rows:
        for skill in (row["skills"] or "").split(", "):
            if skill:
                counts[skill] += 1
    return counts.most_common(n)


def skill_growth_by_week(
    db_path: str = "jobs.db", min_count: int = 5
) -> tuple[list[tuple[str, int, int, float | None]], str | None]:
    """Compare the two most recent COMPLETE weeks of skill discovery.
    min_count: a skill must reach this in at least one of the two weeks to
    be RANKED by percentage — below it, "1 -> 11" reads as a dramatic
    +1000% but is really just noise from a handful of postings. Filtered
    entries aren't discarded from the raw data, only excluded from the
    percentage-sorted view; top_skills() still shows true absolute counts
    for everything, including the long tail."""
    conn = _connect(db_path)
    rows = conn.execute(f"SELECT first_seen, skills FROM jobs WHERE {STATS_WHERE}").fetchall()
    conn.close()

    week_job_counts, week_skill_counts, bootstrap_day = _weekly_first_seen(rows)
    current = _current_week_start()
    complete_weeks = sorted(w for w in week_job_counts if w != current)

    if len(complete_weeks) < 2:
        return [], bootstrap_day

    prev = week_skill_counts.get(complete_weeks[-2], Counter())
    latest = week_skill_counts.get(complete_weeks[-1], Counter())
    results = []
    for skill in set(prev) | set(latest):
        p, l = prev.get(skill, 0), latest.get(skill, 0)
        if min(p, l) < min_count:
            continue  # too small to trust a percentage from — the earlier
            # max() version was wrong: a percentage blows up when the
            # SMALLER of the two counts is tiny (e.g. 1 -> 11 = "+1000%"),
            # regardless of how large the other one is. max() let cases
            # like that straight through since 11 alone cleared the bar.
        pct = ((l - p) / p * 100) if p else None
        results.append((skill, p, l, pct))
    results.sort(key=lambda r: (r[3] is None, -(r[3] or 0)))
    return results, bootstrap_day


def skill_categories(db_path: str = "jobs.db") -> list[tuple[str, int]]:
    from job_scraper.stats.taxonomy import TAXONOMY

    conn = _connect(db_path)
    rows = conn.execute(f"SELECT skills FROM jobs WHERE {STATS_WHERE}").fetchall()
    conn.close()

    counts: Counter[str] = Counter()
    for row in rows:
        seen = set()
        for skill in (row["skills"] or "").split(", "):
            cat = TAXONOMY.get(skill)
            if cat:
                seen.add(cat)
        for cat in seen:
            counts[cat] += 1
    return counts.most_common()


if __name__ == "__main__":
    conn = _connect()
    total_in_scope = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {STATS_WHERE}").fetchone()[0]
    conn.close()

    print("=== Posted-date distribution (snapshot, NOT a trend) ===")
    for week, count in posted_date_distribution():
        print(f"  {week}: {count}")

    print("\n=== Corpus growth by week (first_seen-based) ===")
    growth_weeks, excluded = corpus_growth_by_week()
    if excluded:
        print(f"  (excluded {excluded} as the detected bootstrap-sweep day)")
    accounted = sum(count for _, count, _ in growth_weeks)
    for week, count, complete in growth_weeks:
        tag = "" if complete else "  <- IN PROGRESS, partial"
        print(f"  {week}: {count}{tag}")
    # Self-check: accounted-for jobs (excluded bootstrap day + accounted
    # weeks) must not exceed the known in-scope total. Catches exactly the
    # class of bug found in review — an inflated sum from conflating job
    # count with skill-mention count.
    status = "OK" if accounted <= total_in_scope else "MISMATCH — INVESTIGATE"
    print(f"  [self-check: {accounted} accounted vs {total_in_scope} total in scope -> {status}]")

    print("\n=== Top 10 skills ===")
    for skill, count in top_skills():
        print(f"  {skill}: {count}")

    print("\n=== Skill growth (two most recent COMPLETE weeks) ===")
    growth, excluded2 = skill_growth_by_week()
    if excluded2:
        print(f"  (excluded {excluded2} as the detected bootstrap-sweep day)")
    if not growth:
        print("  not enough complete weekly history yet")
    else:
        for skill, prev, latest, pct in growth[:15]:
            pct_str = f"{pct:+.0f}%" if pct is not None else "new"
            print(f"  {skill}: {prev} -> {latest} ({pct_str})")

    print("\n=== By category ===")
    for cat, count in skill_categories():
        print(f"  {cat}: {count}")


def cv_skill_gap(cv_path: str = "cv.docx", db_path: str = "jobs.db", top_n: int = 20):
    """Diff between top market-demanded skills and what the CV actually
    contains — same unbiased taxonomy run on both sides, so this is a fair
    comparison, not match_cv.py's personal CV-fit-weighted view. Returns
    (have, missing): each a list of (skill, market_count), sorted by
    market_count descending. 'missing' is the direct answer to 'what should
    I add to my CV or build into this project next'."""
    from job_scraper.rag.match_cv import read_cv
    from job_scraper.stats.taxonomy import extract_skills

    cv_skills = set(extract_skills(read_cv(cv_path)))
    market = top_skills(top_n, db_path)

    have = [(s, c) for s, c in market if s in cv_skills]
    missing = [(s, c) for s, c in market if s not in cv_skills]
    return have, missing


if __name__ == "__main__" and "--gap" in __import__("sys").argv:
    have, missing = cv_skill_gap()
    print("=== In your CV, in-demand ===")
    for s, c in have:
        print(f"  \u2713 {s}: {c}")
    print("\n=== In demand, NOT in your CV ===")
    for s, c in missing:
        print(f"  \u2717 {s}: {c}")
