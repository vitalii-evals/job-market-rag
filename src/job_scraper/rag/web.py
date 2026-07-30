"""Minimal LOCAL web UI for the job-market RAG.
Private by design: binds to 127.0.0.1 only — reach it from your laptop via an
SSH tunnel (see run instructions). NOT for public exposure: the RAG returns raw
listing content, which COMPLIANCE.md restricts to private use in Phases 1-3."""
from flask import Flask, request, jsonify

from job_scraper.rag.answer import ask, DEFAULT_K

app = Flask(__name__)

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Market RAG</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root { --bg:#0f1115; --panel:#1a1d24; --text:#e6e6e6; --muted:#8b93a1;
          --accent:#4f9cf9; --border:#2a2f3a; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, sans-serif;
         background:var(--bg); color:var(--text); }
  .wrap { max-width: 820px; margin: 0 auto; padding: 32px 20px 80px; }
  h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
  textarea { width:100%; background:var(--panel); color:var(--text);
             border:1px solid var(--border); border-radius:8px; padding:12px;
             font-size:15px; font-family:inherit; resize:vertical; min-height:56px; }
  .ctrls { display:flex; gap:10px; align-items:center; margin:8px 0 20px; }
  button { background:var(--accent); color:#fff; border:0; border-radius:8px;
           padding:10px 18px; font-size:14px; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  label { color:var(--muted); font-size:13px; }
  select { background:var(--panel); color:var(--text); border:1px solid var(--border);
           border-radius:6px; padding:6px; }
  #answer { background:var(--panel); border:1px solid var(--border); border-radius:8px;
            padding:4px 20px; min-height:60px; line-height:1.55; }
  #answer:empty::before { content:"Ask a question about the job market…"; color:var(--muted); }
  #answer table { border-collapse:collapse; width:100%; margin:12px 0; font-size:14px; }
  #answer th, #answer td { border:1px solid var(--border); padding:6px 10px; text-align:left; }
  #answer code { background:#0b0d11; padding:1px 5px; border-radius:4px; font-size:13px; }
  .status { color:var(--muted); font-size:13px; }
  .err { color:#f97066; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Job Market RAG</h1>
  <div class="sub">Grounded answers over live JustJoin listings · voyage-3.5-lite + claude</div>
  <textarea id="q" placeholder="e.g. What senior LLM roles are hiring in Kraków and what do they pay?"></textarea>
  <div class="ctrls">
    <button id="go">Ask</button>
    <label>listings retrieved
      <select id="k">
        <option>8</option><option selected>12</option><option>16</option><option>20</option>
      </select>
    </label>
    <span class="status" id="status"></span>
  </div>
  <div id="answer"></div>
</div>
<script>
  const q = document.getElementById('q');
  const go = document.getElementById('go');
  const k = document.getElementById('k');
  const status = document.getElementById('status');
  const answer = document.getElementById('answer');

  async function askQuestion() {
    const question = q.value.trim();
    if (!question) return;
    go.disabled = true;
    status.textContent = 'Retrieving + generating…';
    status.className = 'status';
    answer.innerHTML = '';
    try {
      const res = await fetch('/ask', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ question, k: parseInt(k.value, 10) })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'request failed');
      answer.innerHTML = marked.parse(data.answer);
      status.textContent = '';
    } catch (e) {
      status.textContent = 'Error: ' + e.message;
      status.className = 'status err';
    } finally {
      go.disabled = false;
    }
  }

  go.addEventListener('click', askQuestion);
  q.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') askQuestion();
  });
</script>
</body>
</html>"""


@app.route("/")
def index():
    return INDEX_HTML


@app.route("/ask", methods=["POST"])
def ask_endpoint():
    data = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "empty question"}), 400
    k = int(data.get("k", DEFAULT_K))
    try:
        return jsonify({"answer": ask(question, k=k)})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


if __name__ == "__main__":
    # 127.0.0.1 ONLY — private. Do NOT change to 0.0.0.0 without auth + compliance review.
    app.run(host="127.0.0.1", port=8000, debug=False)
