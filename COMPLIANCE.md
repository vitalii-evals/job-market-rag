# Compliance

Diligence record for data sourcing. This project is a **private,
non-commercial, personal portfolio/learning build** — a technical
demonstration of a scraping pipeline + hand-built RAG, not a public
service that republishes third-party content.

## Source: JustJoin.it

**Access method (compliant path):**
- Discovery via the sitemap JustJoin explicitly declares in `robots.txt`
  (`sitemaps/active-jobs.xml`). Job pages under `/job-offer/` are not
  disallowed.
- Data via schema.org `JobPosting` JSON-LD embedded in each page —
  structured data the site publishes for search-engine crawlers.
- `/api/` is `Disallow`ed in robots.txt → **not used.** No internal API,
  no authenticated endpoints, no login.
- No account created → no clickwrap terms accepted.
- Polite: 0.5s delay between requests, once daily, descriptive User-Agent.

**Terms reviewed (primary source):**
JustJoin/RocketJobs *Regulamin świadczenia usług drogą elektroniczną*
(in force 2026-04-01, Polish law — Civil Code + Act on electronic-service
provision). The terms prohibit copying, downloading, or redistributing
App content (incl. databases), in whole or part, without prior written
consent.

**Posture given that clause:**
- This build scrapes into a **private** DB for personal analysis and to
  demonstrate engineering skills. It does not display, republish, or
  redistribute JustJoin's listings.
- Use is private, non-commercial, on publicly-visible data, with no
  account and no acceptance of clickwrap terms — the weaker-enforceability
  zone for browsewrap-style restrictions. Acknowledged: the literal clause
  covers downloading; this use is not *explicitly permitted*, only
  low-risk in practice for private research.

**If ever made public (not currently planned):**
- Publish only **derived aggregates/analysis** (trends, salary bands,
  skill-demand over time) — my analysis, not their content — never raw
  listings.
- Strip recruiter/personal data (GDPR/RODO); link back to the source for
  any actual posting.
- Or obtain written consent before displaying any content.

## Rejected source: Bulldogjob

Fully Cloudflare-gated on live re-verification (2026-07-28): every path
except `robots.txt` returns `403 + cf-mitigated: challenge`. The only
access would require defeating bot protection (headless/spoofing) →
**rejected on compliance grounds.** Compliance is a live property, not a
one-time fact — Bulldogjob passed an earlier check and later rotted.

## Principle

Compliance over coverage. Verify each source live (robots.txt + bot
posture) before building; prefer the cleanest allowed access method;
never bypass bot protection; keep scraping private and polite.
