"""Private stats dashboard — server-rendered HTML, CSS-only bar charts.
No charting library: consistent with this project's hand-built-first
principle, and simple enough at this scale that a library would be
premature abstraction (same reasoning as retrieve.py's numpy-over-vector-DB
choice). Renders fresh on every request — corpus is ~3k rows, queries run
in well under a second, no caching needed for single-operator traffic."""
from job_scraper.stats.queries import (
    total_jobs_in_scope, top_skills, skill_categories,
    corpus_growth_by_week, skill_growth_by_week,
)


def _bar(label: str, value: int, max_value: int) -> str:
    pct = round(100 * value / max_value) if max_value else 0
    return f'''
    <div class="bar-row">
      <div class="bar-label">{label}</div>
      <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
      <div class="bar-value">{value}</div>
    </div>'''


def _mover_row(skill: str, prev: int, latest: int, pct: float | None) -> str:
    direction = "up" if (pct or 0) >= 0 else "down"
    arrow = "\u25b2" if direction == "up" else "\u25bc"
    pct_str = f"{pct:+.0f}%" if pct is not None else "new"
    return f'''
    <div class="mover-row">
      <span class="mover-skill">{skill}</span>
      <span class="mover-counts">{prev} \u2192 {latest}</span>
      <span class="mover-pct {direction}">{arrow} {pct_str}</span>
    </div>'''


def render_dashboard(db_path: str = "jobs.db") -> str:
    total = total_jobs_in_scope(db_path)
    skills = top_skills(10, db_path)
    categories = skill_categories(db_path)
    weeks, bootstrap_excluded = corpus_growth_by_week(db_path)
    movers, _ = skill_growth_by_week(db_path)

    max_skill = max((c for _, c in skills), default=1)
    max_cat = max((c for _, c in categories), default=1)
    max_week = max((c for _, c, _ in weeks), default=1)

    skills_html = "".join(_bar(s, c, max_skill) for s, c in skills)
    categories_html = "".join(_bar(c, n, max_cat) for c, n in categories)

    weeks_html = ""
    for week, count, complete in weeks:
        label = week if complete else f'{week} <span class="partial-tag">in progress</span>'
        weeks_html += _bar(label, count, max_week)

    movers_html = "".join(_mover_row(s, p, l, pct) for s, p, l, pct in movers[:10])
    if not movers_html:
        movers_html = '<div class="empty">Not enough complete weekly history yet — check back as the corpus grows.</div>'

    bootstrap_note = (
        f'<div class="note">Excludes {bootstrap_excluded} — the one-time initial discovery sweep, not organic growth.</div>'
        if bootstrap_excluded else ""
    )

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Automation Job Market — Stats</title>
<style>
  :root {{ --bg:#0f1115; --panel:#1a1d24; --text:#e6e6e6; --muted:#8b93a1;
          --accent:#4f9cf9; --border:#2a2f3a; --up:#3ecf8e; --down:#f97066; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: system-ui, -apple-system, sans-serif;
         background:var(--bg); color:var(--text); }}
  .wrap {{ max-width: 900px; margin: 0 auto; padding: 32px 20px 80px; }}
  nav {{ margin-bottom: 24px; font-size: 13px; }}
  nav a {{ color: var(--muted); text-decoration: none; margin-right: 16px; }}
  nav a.active {{ color: var(--accent); font-weight: 600; }}
  h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); font-size: 13px; }}
  .headline {{ font-size: 34px; font-weight: 700; margin: 20px 0 2px; }}
  .headline-label {{ color: var(--muted); font-size: 13px; margin-bottom: 24px; }}
  h2 {{ font-size: 14px; font-weight: 600; margin: 32px 0 12px; color: var(--text);
       border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
  .panel {{ background:var(--panel); border:1px solid var(--border);
           border-radius:8px; padding:16px 20px; }}
  .bar-row {{ display:flex; align-items:center; gap:10px; margin:8px 0; font-size:13px; }}
  .bar-label {{ width: 170px; flex-shrink:0; }}
  .bar-track {{ flex:1; background:#0b0d11; border-radius:4px; height:14px; overflow:hidden; }}
  .bar-fill {{ background:var(--accent); height:100%; border-radius:4px; }}
  .bar-value {{ width: 50px; text-align:right; color:var(--muted); flex-shrink:0; }}
  .partial-tag {{ color: var(--muted); font-size: 11px; font-style: italic; }}
  .mover-row {{ display:flex; align-items:center; gap:12px; padding:7px 0;
               border-bottom:1px solid var(--border); font-size:13px; }}
  .mover-row:last-child {{ border-bottom: none; }}
  .mover-skill {{ width: 170px; flex-shrink:0; }}
  .mover-counts {{ color: var(--muted); width: 90px; flex-shrink:0; }}
  .mover-pct {{ font-weight: 600; }}
  .mover-pct.up {{ color: var(--up); }}
  .mover-pct.down {{ color: var(--down); }}
  .note {{ color: var(--muted); font-size: 12px; margin-top: 10px; font-style: italic; }}
  .empty {{ color: var(--muted); font-size: 13px; padding: 8px 0; }}
</style>
</head>
<body>
<div class="wrap">
  <nav><a href="/">RAG chat</a><a href="/stats" class="active">Market stats</a></nav>
  <h1>AI Automation Job Market — Poland</h1>
  <div class="sub">JustJoin · AI/automation core tier, real tech stack detected only</div>

  <div class="headline">{total}</div>
  <div class="headline-label">jobs currently tracked in scope</div>

  <h2>Top skills in demand</h2>
  <div class="panel">{skills_html}</div>

  <h2>By category</h2>
  <div class="panel">{categories_html}</div>

  <h2>Corpus growth by week</h2>
  <div class="panel">{weeks_html}{bootstrap_note}</div>

  <h2>Fastest-growing skills (week over week)</h2>
  <div class="panel">{movers_html}</div>
</div>
</body>
</html>'''
