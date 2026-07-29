# job-market-rag — build notes

Design decisions and mental model for the daily job-scraping pipeline.
Written to defend in interviews and to remember *why*, not just *what*.

## Goal

A compliant daily pipeline that scrapes AI/data/automation-relevant IT
job listings into a queryable SQLite DB — the foundation for a
hand-built RAG (Phase 2).

## Core logic (the order I proceeded in)

0. **Sources are not stable — verify live before trusting them.**
   Bulldogjob looked clean a week earlier; on live re-check it was
   fully Cloudflare-gated. Compliance is a *live* property, not a
   one-time fact. Always re-probe robots.txt + bot posture before building.

1. **Find sources that allow scraping (no compliance break).**
   Read robots.txt, check for Cloudflare/bot challenges live. JustJoin:
   job pages allowed, `/api/` disallowed, sitemap explicitly declared.

2. **Per source, pick the optimal access method.**
   Access methods, cleanest → messiest: official API > sitemap + JSON-LD
   > internal/undocumented API > raw HTML scraping > headless browser.
   JustJoin path = **sitemap for discovery + schema.org JobPosting JSON-LD
   for data**. No API (disallowed), no raw-HTML scraping, no headless
   browser. JSON-LD is structured data the site publishes for Google —
   machine-readable, stable across redesigns, standardized.

3. **Decide the schema — split into reversible vs. non-retrofittable.**
   - (a) Data fields I can `ALTER TABLE ADD` anytime later.
   - (b) The few I must get right up front:
     - `first_seen`/`last_seen` — history I can only record going forward.
     - PK `source:slug` — identity that makes re-scraping idempotent.
   Get (b) right on day 1; (a) can evolve.

4. **Decide what to store vs. filter.**
   Chose **store-all-fetched, filter-at-query.** One gate only: the fetch
   net. Everything fetched gets stored — no second storage filter.
   A discarded job leaves no trace (no `first_seen`), and lost history is
   permanent while stored-but-unwanted data is ~5KB and reversible.
   Relevance is a query-time concern (`WHERE match_tier=...`), not storage.

## Architecture (source-adapter pattern)

    sitemap → slug-filter → fetch JSON-LD → common schema → upsert

- `store.py` — schema + idempotent upsert. Knows nothing about sources.
- `adapters/justjoin.py` — all JustJoin-specific logic. Returns
  common-schema dicts. Adding a source = one new adapter, zero pipeline
  changes.
- `main.py` — orchestration + CLI entry point.
- `run_scrape.sh` — cron wrapper (absolute paths, cd, logged).

### Two-stage relevance

- **Fetch net (`_classify_slug`)** — coarse, permissive. Scans the whole
  ~10k sitemap, keeps only slugs matching core/adjacent keywords minus
  excludes. Decides what to *fetch* (a cost/politeness decision). Slug
  matching is lossy; we accept slug false-negatives (cost: one job), never
  content false-negatives.
- **Content relevance (Phase 2)** — the RAG's semantic retrieval refines
  what the coarse net let through.

Tiers: `core` (ai/ml/llm/rag/genai/mlops/automation…),
`adjacent` (python/data-engineer/backend…), excludes (tutoring/sales/etc).

## Schema

    id              TEXT PRIMARY KEY   -- "source:slug"
    source          TEXT NOT NULL
    title           TEXT NOT NULL
    company         TEXT
    description     TEXT               -- HTML-unescaped plain text
    locations       TEXT               -- comma-joined
    employment_type TEXT
    skills          TEXT               -- null from JSON-LD; sourced later
    salary_min/max  INTEGER
    currency        TEXT
    posted_date     TEXT               -- datePosted
    valid_through   TEXT               -- validThrough
    url             TEXT
    raw_json        TEXT               -- re-parse insurance
    match_tier      TEXT               -- 'core'|'adjacent'; why fetched, refreshed
    first_seen      TEXT               -- set once, never updated
    last_seen       TEXT               -- refreshed every scrape

### Interview-defense points

- **Composite `source:slug` PK** → cross-source dedup without collisions;
  the hinge idempotency swings on (INSERT first time, UPDATE thereafter).
- **`first_seen`/`last_seen`** → temporal dimension for trend analysis;
  non-retrofittable, so designed up front. `first_seen` frozen,
  `last_seen` refreshed.
- **`raw_json`** → re-parse without re-scraping if requirements change.
- **`source` column** → source-agnostic pipeline; adapters tag origin.
- **`match_tier`** → query-time relevance without discarding data;
  *refreshed* on re-scrape (unlike `first_seen`) because classification
  rules evolve — freezing would strand old rows under retired definitions.
- **Schema evolved live via `ALTER TABLE ADD COLUMN`** (not drop-rebuild)
  → migrated a populated table without losing `first_seen` history;
  pre-filter rows correctly carry `match_tier = NULL`.

## Known limitations (fix in Phase 2)

- JSON-LD `description` fuses words where block tags were stripped
  (`DeveloperaTwój`). Needs whitespace repair before embedding.
- Slug net has false-positives (e.g. test-`automation` QA roles land in
  core). Content-relevance layer handles this.
- Company casing splits (`KODLAND` vs `Kodland`) — normalize at query time
  (`LOWER(TRIM(company))`), never at ingest.

## Infra

- Self-hosted on Vultr VPS (Ubuntu, Docker, uv).
- Daily cron 04:00 UTC via `run_scrape.sh`, logged to `logs/`.
- `--limit 3000` ceiling; ~2.2k relevant jobs captured full-board.
