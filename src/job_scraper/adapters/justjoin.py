
import html
import re

import httpx
from lxml import etree

SITEMAP_INDEX = "https://justjoin.it/sitemaps/active-jobs.xml"

# Honest, descriptive UA — declares what we are, per compliance principle.
HEADERS = {"User-Agent": "job-scraper/0.1 (+research; personal project)"}

# The sitemap XML namespace — lxml requires this to match <loc> elements.
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _get(client: httpx.Client, url: str) -> bytes:
    """Fetch raw bytes, following the 307 redirect to the CDN host."""
    resp = client.get(url, headers=HEADERS, follow_redirects=True, timeout=30.0)
    resp.raise_for_status()
    return resp.content


def _extract_locs(xml_bytes: bytes) -> list[str]:
    """Parse sitemap XML, return all <loc> text values (works for both
    <sitemapindex> and <urlset> — both use <loc> under the same namespace)."""
    root = etree.fromstring(xml_bytes)
    return [loc.text for loc in root.findall(".//sm:loc", NS)]


def discover_job_urls(
    client: httpx.Client,
    limit: int | None = None,
    hard_ceiling: int = 8000,
) -> list[tuple[str, str]]:
    """Two-level walk: index sitemap → child sitemaps → job URLs.

    Scans the WHOLE sitemap, but keeps only URLs whose slug passes the
    relevance net (_classify_slug). Returns (url, tier) pairs.

    limit: cap matched urls — for testing only; production passes None.
    hard_ceiling: runaway guard. If matches exceed this, the slug net is
        almost certainly broken (matching everything), so stop and warn
        loudly rather than silently fetch 10k+ pages. Not a normal cap —
        legitimate growth should never approach it.
    """
    index_locs = _extract_locs(_get(client, SITEMAP_INDEX))

    matched: list[tuple[str, str]] = []
    for child_sitemap in index_locs:
        for url in _extract_locs(_get(client, child_sitemap)):
            slug = _native_id(url)
            tier = _classify_slug(slug)
            if tier is not None:
                matched.append((url, tier))
                if limit is not None and len(matched) >= limit:
                    return matched
                if len(matched) >= hard_ceiling:
                    print(
                        f"  WARNING: matched {len(matched)} jobs, hit "
                        f"hard_ceiling={hard_ceiling}. Slug net may be broken. "
                        f"Stopping discovery."
                    )
                    return matched

    return matched

    return matched

import json
from urllib.parse import urlparse

# JSON-LD lives in a <script type="application/ld+json"> tag.
JSONLD_XPATH = '//script[@type="application/ld+json"]/text()'


def _native_id(url: str) -> str:
    """Slug after /job-offer/ is the stable unique key."""
    return urlparse(url).path.rstrip("/").split("/job-offer/")[-1]


def _first(value):
    """schema.org fields can be a single object or a list of them.
    Return the first if it's a list, else the value unchanged."""
    return value[0] if isinstance(value, list) else value


def _parse_salary(base: dict | None) -> tuple[int | None, int | None, str | None, str | None]:
    """Extract (min, max, currency, period) from baseSalary, tolerating absence.
    period = schema.org unitText (HOUR/DAY/WEEK/MONTH/YEAR) or None."""
    if not base:
        return None, None, None, None
    val = base.get("value") or {}
    period = val.get("unitText")
    if period not in {"HOUR", "DAY", "WEEK", "MONTH", "YEAR"}:
        period = None  # reject unexpected/garbage values, mirror backfill logic
    return val.get("minValue"), val.get("maxValue"), base.get("currency"), period

def _parse_locations(job_location) -> str | None:
    """jobLocation may be one Place or a list. Return comma-joined cities."""
    if not job_location:
        return None
    places = job_location if isinstance(job_location, list) else [job_location]
    cities = [
        (p.get("address") or {}).get("addressLocality")
        for p in places
    ]
    cities = [c for c in cities if c]  # drop None/empty
    return ", ".join(cities) if cities else None

def _parse_location_type(posting: dict) -> str | None:
    """Map schema.org jobLocationType to 'remote' | 'onsite' | None.
    TELECOMMUTE -> remote; physical location present -> onsite; else None."""
    if posting.get("jobLocationType") == "TELECOMMUTE":
        return "remote"
    if posting.get("jobLocation"):
        return "onsite"
    return None

# Not part of schema.org JobPosting — JustJoin doesn't expose seniority via JSON-LD.
# Lives in the page's Next.js RSC stream (__next_f.push chunks) as a double-escaped
# JSON fragment: \"experienceLevel\":{\"label\":...,\"value\":...}. Appears once per
# page for the primary job; the related-jobs sidebar uses a flat string form
# (\"experienceLevel\":\"senior\") not matched by this pattern — verified across 5
# test pages, single match each, correct values in every case.
EXPERIENCE_LEVEL_RE = re.compile(
    rb'\\"experienceLevel\\":\{\\"label\\":\\"[a-zA-Z_]*\\",\\"value\\":\\"([a-zA-Z_]*)\\"\}'
)


def _parse_experience_level(page_bytes: bytes) -> str | None:
    """Extract experienceLevel from raw page bytes. Undocumented internal payload
    shape, not a stable contract like JSON-LD — more fragile than other extractors
    here. Returns None silently on shape drift rather than crashing; watch for a
    drop in non-null coverage after a scrape as the signal something broke."""
    match = EXPERIENCE_LEVEL_RE.search(page_bytes)
    return match.group(1).decode() if match else None


def _unescape(s: str | None) -> str | None:
    """Decode HTML entities (&amp; -> &) from JSON-LD text fields."""
    return html.unescape(s) if s else None


def fetch_job(client: httpx.Client, url: str, tier: str | None = None) -> dict | None:
    """Fetch one job page, extract JobPosting JSON-LD, map to common schema.
    Returns None if the page has no parseable JobPosting (skip, don't crash)."""
    # renamed html -> page_bytes: needed as raw bytes for the experience_level regex
    # below, and the old name silently shadowed the module-level `html` import
    page_bytes = _get(client, url)
    tree = etree.HTML(page_bytes)

    blocks = tree.xpath(JSONLD_XPATH)
    posting = None
    for raw in blocks:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            posting = data
            break

    if posting is None:
        return None  # not a job page, or schema changed — caller skips it

    salary_min, salary_max, currency, salary_period = _parse_salary(posting.get("baseSalary"))
    org = _first(posting.get("hiringOrganization")) or {}
    experience_level = _parse_experience_level(page_bytes)

    return {
        "id": f"justjoin:{_native_id(url)}",
        "source": "justjoin",
        "title": _unescape(posting.get("title")),
        "company": org.get("name") if isinstance(org, dict) else None,
        "description": _unescape(posting.get("description")),
        "locations": _parse_locations(posting.get("jobLocation")),
        "location_type": _parse_location_type(posting),
        "experience_level": experience_level,
        "employment_type": posting.get("employmentType"),
        "skills": None,  # not present in JSON-LD; sourced later if needed
        "salary_min": salary_min,
        "salary_max": salary_max,
        "currency": currency,
        "salary_period": salary_period,
        "posted_date": posting.get("datePosted"),
        "valid_through": posting.get("validThrough"),
        "url": url,
        "raw_json": json.dumps(posting, ensure_ascii=False),
        "match_tier": tier,
    }


import time


def scrape(limit: int | None = None, delay: float = 0.5) -> list[dict]:
    """Full JustJoin scrape: discover live job URLs, fetch+map each.

    limit: cap number of matched jobs (Phase-1 politeness; 10k+ live).
    delay: seconds between page fetches (rate-limit courtesy).
    Returns common-schema dicts ready for store.upsert_jobs().
    """
    with httpx.Client() as client:
        pairs = discover_job_urls(client, limit=limit)

        jobs: list[dict] = []
        for i, (url, tier) in enumerate(pairs, 1):
            try:
                job = fetch_job(client, url, tier)
            except httpx.HTTPError as e:
                print(f"  [{i}/{len(pairs)}] FETCH ERROR {url}: {e}")
                continue
            if job is None:
                print(f"  [{i}/{len(pairs)}] no JobPosting, skipped: {url}")
                continue
            jobs.append(job)
            print(f"  [{i}/{len(pairs)}] ok: {job['title']} @ {job['company']}")
            time.sleep(delay)

    return jobs


# --- Slug-based relevance prefilter -----------------------------------------
# HARD_EXCLUDE always wins, regardless of any core/adjacent hit — these terms
# describe the ROLE ITSELF (teaching, sales, support), so a CORE keyword
# alongside them means "AI-adjacent sales/support job", not a build role.
HARD_EXCLUDE_KEYWORDS = (
    "korepetytor", "nauczyciel", "manager-zajec", "zajec-probnych",
    "sales", "account-manager", "helpdesk", "service-desk",
    "recruiter", "specialist-salae",
)
# SOFT_EXCLUDE only wins when there's NO core hit — these terms describe WHO
# the role serves (marketing/HR as internal client) or collide with company
# names (e.g. "smart-hr"), not what the role does. Verified 2026-08-12: of
# 28 slugs with a real CORE hit dropped by an exclude, 18/28 were 'sales'
# (Salesforce-platform/presales noise, kept hard) vs 11/28 marketing+hr-
# (real misses, e.g. an internal AI-automation-integration-engineer role
# whose team happens to be "marketing" — the Comarch-shaped target case).
SOFT_EXCLUDE_KEYWORDS = ("marketing", "hr-")
CORE_KEYWORDS = (
    "ai", "ml", "machine-learning", "llm", "genai", "gen-ai",
    "rag", "nlp", "data-scien", "mlops", "automation", "rpa",
    # Polish stems — SKILL_VOCAB in match_cv.py already scores "automatyzacj"
    # (added during the Comarch validation session) but the fetch net never
    # got the matching update, so Polish-titled automation roles never
    # reached the DB to be scored at all. Verified 2026-08-12: adds 22
    # previously-invisible slugs, including several Comarch-shaped internal
    # automation/orchestration roles (upvanta x5, adamed, enea x2, asseco).
    "automatyzacj", "orkiestracj", "robotyzacj",
)
ADJACENT_KEYWORDS = (
    "python", "data-engineer", "data-eng", "backend", "back-end",
)


def _classify_slug(slug: str) -> str | None:
    """Return 'core' | 'adjacent' if the slug passes the net, else None.
    HARD excludes always win. SOFT excludes win only when there's no CORE
    hit alongside them — ADJACENT hits do NOT override soft excludes (a
    weaker signal; e.g. a data-engineer role for marketing analytics is
    genuinely not the target, unlike an ai/automation-titled role that
    happens to serve a marketing team)."""
    s = slug.lower()
    if any(kw in s for kw in HARD_EXCLUDE_KEYWORDS):
        return None
    tokens = s.split("-")

    def _has(keywords: tuple[str, ...]) -> bool:
        for kw in keywords:
            if "-" in kw or len(kw) > 3:
                if kw in s:
                    return True
            else:
                if kw in tokens:
                    return True
        return False

    has_core = _has(CORE_KEYWORDS)
    if any(kw in s for kw in SOFT_EXCLUDE_KEYWORDS) and not has_core:
        return None

    if has_core:
        return "core"
    if _has(ADJACENT_KEYWORDS):
        return "adjacent"
    return None
