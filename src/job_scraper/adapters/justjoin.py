
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


def discover_job_urls(client: httpx.Client, limit: int | None = None) -> list[str]:
    """Two-level walk: index sitemap → child sitemaps → job-page URLs.

    limit caps the number of job URLs returned (Phase-1 politeness; 10k+ live).
    """
    index_locs = _extract_locs(_get(client, SITEMAP_INDEX))  # -> [part0.xml, ...]

    job_urls: list[str] = []
    for child_sitemap in index_locs:
        job_urls.extend(_extract_locs(_get(client, child_sitemap)))
        if limit is not None and len(job_urls) >= limit:
            break

    return job_urls[:limit] if limit is not None else job_urls


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


def _parse_salary(base: dict | None) -> tuple[int | None, int | None, str | None]:
    """Extract (min, max, currency) from baseSalary, tolerating absence."""
    if not base:
        return None, None, None
    val = base.get("value") or {}
    return val.get("minValue"), val.get("maxValue"), base.get("currency")


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


def fetch_job(client: httpx.Client, url: str) -> dict | None:
    """Fetch one job page, extract JobPosting JSON-LD, map to common schema.
    Returns None if the page has no parseable JobPosting (skip, don't crash)."""
    html = _get(client, url)
    tree = etree.HTML(html)

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

    salary_min, salary_max, currency = _parse_salary(posting.get("baseSalary"))
    org = _first(posting.get("hiringOrganization")) or {}

    return {
        "id": f"justjoin:{_native_id(url)}",
        "source": "justjoin",
        "title": posting.get("title"),
        "company": org.get("name") if isinstance(org, dict) else None,
        "description": posting.get("description"),
        "locations": _parse_locations(posting.get("jobLocation")),
        "employment_type": posting.get("employmentType"),
        "skills": None,  # not present in JSON-LD; sourced later if needed
        "salary_min": salary_min,
        "salary_max": salary_max,
        "currency": currency,
        "posted_date": posting.get("datePosted"),
        "valid_through": posting.get("validThrough"),
        "url": url,
        "raw_json": json.dumps(posting, ensure_ascii=False),
    }


import time


def scrape(limit: int | None = None, delay: float = 0.5) -> list[dict]:
    """Full JustJoin scrape: discover live job URLs, fetch+map each.

    limit: cap number of jobs (Phase-1 politeness; 10k+ live).
    delay: seconds between page fetches (rate-limit courtesy).
    Returns common-schema dicts ready for store.upsert_jobs().
    """
    with httpx.Client() as client:
        urls = discover_job_urls(client, limit=limit)

        jobs: list[dict] = []
        for i, url in enumerate(urls, 1):
            try:
                job = fetch_job(client, url)
            except httpx.HTTPError as e:
                print(f"  [{i}/{len(urls)}] FETCH ERROR {url}: {e}")
                continue
            if job is None:
                print(f"  [{i}/{len(urls)}] no JobPosting, skipped: {url}")
                continue
            jobs.append(job)
            print(f"  [{i}/{len(urls)}] ok: {job['title']} @ {job['company']}")
            time.sleep(delay)

    return jobs
