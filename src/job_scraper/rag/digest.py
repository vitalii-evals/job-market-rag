"""Daily Telegram digest: today's fresh, junior-accessible, on-stack job
matches, pushed automatically. Reuses match_cv.py's rank_jobs() wholesale —
this module only formats and sends."""
import os
import sys

import requests

from job_scraper.rag.match_cv import rank_jobs
from job_scraper.rag.answer import _format_salary

TOP_N = 6
DAYS = 1


def _telegram_send(text: str) -> bool:
    """Send a message via the Telegram Bot API. Returns True on success."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",       # allows <a href="...">links</a>
            "disable_web_page_preview": True,  # avoid a big preview card per link
        },
        timeout=15,
    )
    ok = resp.status_code == 200 and resp.json().get("ok")
    if not ok:
        print(f"Telegram send failed: {resp.status_code} {resp.text}")
    return ok


def _format_job_block(rank: int, job: dict) -> str:
    """One job as a compact HTML block for Telegram."""
    sal = _format_salary(job)
    n_match, n_total, matched_skills = job["skill_matches"]
    jr_tag = " 🎯 JUNIOR" if job["seniority"] == "junior" else ""
    title = job["title"]
    company = job["company"]
    url = job["url"]
    loc = job["locations"] or "location n/a"
    return (
        f"<b>{rank}. {title}</b> @ {company}{jr_tag}\n"
        f"{loc} | {sal}\n"
        f"skills: {n_match}/{n_total}\n"
        f'<a href="{url}">Apply</a>'
    )


def build_digest_text(top_n: int = TOP_N, days: int = DAYS) -> str:
    """Rank today's matches and format the full digest message."""
    jobs = rank_jobs(top_n=top_n, days=days)

    if not jobs:
        return f"📭 No new junior-accessible matches in the last {days} day(s)."

    header = f"🎯 <b>{len(jobs)} new matches</b> (last {days}d, Kraków/remote, junior-friendly)\n"
    blocks = [_format_job_block(i, job) for i, job in enumerate(jobs, 1)]
    return header + "\n\n".join(blocks)


def send_digest(top_n: int = TOP_N, days: int = DAYS) -> bool:
    text = build_digest_text(top_n=top_n, days=days)
    return _telegram_send(text)


if __name__ == "__main__":
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else TOP_N
    days = int(sys.argv[2]) if len(sys.argv) > 2 else DAYS
    ok = send_digest(top_n=top_n, days=days)
    sys.exit(0 if ok else 1)
