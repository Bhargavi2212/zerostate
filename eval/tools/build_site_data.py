"""Build site/ (static, Vercel root): the console from ui/ in recorded-replay mode + the results page.

    python eval/tools/build_site_data.py [--out site]

Data: the real API in replay mode, in-process (FastAPI TestClient, no network), over the bundles in
EPISODES; every GET the console makes is saved as a JSON file under site/data/. The results page is
rendered only from eval/results/score_<batch>.json. The build fails on any never-say hit or key-like string.
"""

import argparse
import gzip
import html
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "src"))

from zerostate.wording import hits

BANNER = "Recorded replay of benchmark runs on simulated plants. Read-only. Nothing here is live."
RESULTS = ROOT / "eval" / "results"
EPISODES = [  # (bundle, what it shows)
    (RESULTS / "bench/p1/S0_seed1184053442_20261103T071508/bundle.json.gz", "clean job (S0), batch p1"),
    (RESULTS / "bench/2/S8_seed1470975726_20261104T050105/bundle.json.gz",
     "feedback lied (S8), batch 2: the data-only and with-camera tracks both block"),
    (RESULTS / "bench/2/S7_seed1263244227_20261104T051135/bundle.json.gz", "a required step skipped / out of order (S7), batch 2"),
    (RESULTS / "bench/p2/S4-small_seed1013371090_20261104T102033/bundle.json.gz", "small passing valve on the P2 gas line (S4-small), batch p2"),
]
BATCHES = [("p1", "bench-freeze-p1"), ("2", "bench-freeze-2"), ("p2", "bench-freeze-p2b and bench-freeze-p2c")]
KEYLIKE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|Bearer\s+\S+|MODEL_API_KEY\s*[=:]\s*\S+)")
UI_FILES = ["app.js", "lib.js", "job.js", "plant.js", "chart.js", "style.css"]  # intake.js (import/confirm) and check.js (request box, model calls) are left out

# (file, regex, replacement): every pattern must match exactly once, so a ui/ change can't slip a control through
PATCHES = [
    ("app.js", r'import \{ intakeScreen \} from "\./intake\.js";\n', ""),
    ("app.js", r'    else if \(path === "/new"\) await intakeScreen\(app\);\n', ""),
    ("app.js", r'import \{ checkScreen \} from "\./check\.js";\n', ""),
    ("app.js", r"\(job\),\n// #/check\[\?session=<id>\] \(check my isolation\)\.", "(job)."),
    ("app.js", r'    else if \(path === "/check"\) cleanup = await checkScreen\(app, params\);\n', ""),
    ("app.js", r'"Sessions"\)\);', '"Recorded episodes"));'),
    ("app.js", r"No sessions yet\. Start with a new isolation\.", "No recorded episodes in this build."),
    ("job.js", r", and the Sign dialog\.", ". Site copy: recorded replay, no write controls."),
    ("job.js", r"const SIGN_ROLES = .*?\n", ""),
    ("job.js", r"    \} else \{\n      const tr = tracks\(\);.*?\n    \}\n(?=    if \(st\.msg\))",
     '    } else out.push(el("p", { class: "muted", id: "replay-note" }, "Recorded replay: nothing can be marked, verified or closed here."));\n'),
    ("job.js", r',\n        el\("td", \{\}, live && !x\.marked_by.*?"Verify"\) : null\)', ""),
    ("job.js", r'"Findings", ""\]', '"Findings"]'),
    ("job.js", r',\n        el\("td", \{\}, el\("button", \{ type: "button", class: "explain-btn".*?"Explain"\)\)', ""),
    ("job.js", r'"Time", ""\]', '"Time"]'),
    ("job.js", r"  // ---------- explain \(screen C\).*?(?=  // ---------- refresh \+ stream)",
     '  parts.explain.append(el("h2", {}, "Explain"), el("p", { class: "small muted" }, "Explain needs the model; it is not part of this recorded replay."));\n\n'),
    ("job.js", r'"Live stream: connected"', '"Recorded events: loading"'),
    ("job.js", r"`Live stream: \$\{why\}`", "`Recorded events: ${why}`"),
    ("job.js", r'es\.onerror = end\("closed"\);', 'es.onerror = end("all shown");'),
]

SHIM = r"""// Site only: maps the console's GET /api/... calls onto the recorded files under data/; every write is refused.
// The event stream becomes a recorded event list (data/sessions/<id>/stream.json), played at ?speed=N if given.
(() => {
  const realFetch = window.fetch.bind(window);
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  function file(path) {
    let m;
    if (path === "/api/sessions") return "data/sessions.json";
    if ((m = path.match(/^\/api\/plants\/([\w-]+)\/map$/))) return `data/plants/${m[1]}/map.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/camera\/(\d+)$/))) return `data/sessions/${m[1]}/camera/${m[2]}.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/stream(\?.*)?$/))) return `data/sessions/${m[1]}/stream.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)$/))) return `data/sessions/${m[1]}/detail.json`;
    return null;
  }
  window.fetch = (path, init = {}) => {
    if (typeof path !== "string" || !path.startsWith("/api/")) return realFetch(path, init);
    if ((init.method || "GET").toUpperCase() !== "GET") return Promise.resolve(json(409, { error: "replay", detail: "recorded replay: read-only" }));
    const f = file(path);
    return f ? realFetch(f) : Promise.resolve(json(404, { error: "not_found", detail: "not in this recorded replay" }));
  };
  class RecordedEvents {
    constructor(url) {
      this.listeners = {}; this.onerror = null; this.closed = false;
      const speed = Number(new URL(url, location.href).searchParams.get("speed")) || 0;
      window.fetch(url).then((r) => r.json()).then(async (list) => {
        let prev = null;
        for (const e of list) {
          const t = JSON.parse(e.data).t;
          if (speed && prev !== null && typeof t === "number") await new Promise((ok) => setTimeout(ok, Math.max(0, (t - prev) * 1000 / speed)));
          if (typeof t === "number") prev = t;
          if (this.closed) return;
          for (const fn of this.listeners[e.event] || []) fn({ data: e.data });
        }
        if (!this.closed && this.onerror) this.onerror();
      });
    }
    addEventListener(kind, fn) { (this.listeners[kind] = this.listeners[kind] || []).push(fn); }
    close() { this.closed = true; }
  }
  window.EventSource = RecordedEvents;
})();
"""

CSS = """
.replay-banner { background: #333; color: #fff; padding: 6px 12px; font-weight: bold; }
.results { max-width: 1100px; margin: 0 auto; padding: 0 12px; }
.results code, .results pre { background: #eee; padding: 2px 4px; white-space: pre-wrap; word-break: break-all; }
"""


def _get(client, path: str):
    r = client.get(path)
    if r.status_code != 200:
        raise SystemExit(f"GET {path}: {r.status_code} {r.text[:200]}")
    return r


def _sse(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        ev = {k: v for k, _, v in (line.partition(": ") for line in block.splitlines()) if k in ("event", "data")}
        if "event" in ev:
            out.append({"event": ev["event"], "data": ev["data"]})
    return out


def api_files(bundles: list[Path]) -> dict[str, object]:
    """{relative path under site/: JSON value} from the real API in replay mode."""
    from fastapi.testclient import TestClient

    from zerostate.api import server

    out: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for b in bundles:
            (tmp / "bundles" / b.parent.name).mkdir(parents=True)
            shutil.copy(b, tmp / "bundles" / b.parent.name / b.name)
        client = TestClient(server.create_app(tmp, tmp / "audit.sqlite", tmp, {}, replay_dir=tmp / "bundles"))
        sessions = _get(client, "/api/sessions").json()
        out["data/sessions.json"] = sessions
        for s in sessions:
            sid = s["id"]
            d = _get(client, f"/api/sessions/{sid}").json()
            out[f"data/sessions/{sid}/detail.json"] = d
            out[f"data/plants/{d['plant']}/map.json"] = _get(client, f"/api/plants/{d['plant']}/map").json()
            out[f"data/sessions/{sid}/stream.json"] = _sse(_get(client, f"/api/sessions/{sid}/stream").text)
            for eid in sorted({f["eval_id"] for f in d["findings"] if f["source"] == "camera"}):
                out[f"data/sessions/{sid}/camera/{eid}.json"] = _get(client, f"/api/sessions/{sid}/camera/{eid}").json()
    return out


def patched_ui() -> dict[str, str]:
    files = {n: (ROOT / "ui" / n).read_text(encoding="utf-8") for n in UI_FILES}
    for name, pat, new in PATCHES:
        files[name], n = re.subn(pat, lambda m, new=new: new, files[name], flags=re.DOTALL)
        if n != 1:
            raise SystemExit(f"site patch for {name} matched {n} times (ui/ changed?): {pat[:60]}")
    files["style.css"] += CSS
    page = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    for old, new in [("<title>ZeroState console</title>", "<title>ZeroState recorded replay</title>"),
                     ("<body>\n", f'<body>\n<div class="replay-banner" id="replay-banner">{BANNER}</div>\n'),
                     ('<nav><a href="#/">Sessions</a> <a href="#/new">New isolation</a> <a href="#/check">Check my isolation</a></nav>',
                      '<nav><a href="index.html#/">Episodes</a> <a href="results.html">Results</a></nav>'),
                     ('<script type="module" src="app.js">', '<script src="replay.js"></script>\n<script type="module" src="app.js">')]:
        if page.count(old) != 1:
            raise SystemExit(f"site patch for index.html: {old!r} not found once")
        page = page.replace(old, new)
    files["index.html"], files["replay.js"] = page, SHIM
    return files


# ---- results page: every number is a <span data-k="path.in.score.json"> copied from the score file
def _v(score: dict, key: str):
    v = score
    for part in key.split("."):
        v = v[part]
    return v


def _n(score: dict, key: str) -> str:
    return f'<span data-k="{html.escape(key)}">{html.escape(str(_v(score, key)))}</span>'


def _rate(score: dict, key: str) -> str:
    return (f"{_n(score, key + '.k')} / {_n(score, key + '.n')} "
            f"(Wilson 95 % CI {_n(score, key + '.ci_low')} to {_n(score, key + '.ci_high')})")


def batch_section(batch: str, tag: str, score: dict, sealed_hash: str) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(sc)}</td>" + "".join(f"<td>{_n(score, f'per_scenario.{sc}.{k}')}</td>"
                                         for k in ("n", "blocked", "escalated", "no_discrepancy", "match")) + "</tr>"
        for sc in score["per_scenario"])
    defs = score.get("definitions", {})
    out = [f'<section class="batch" data-batch="{e(batch)}"><h2>Batch {e(batch)}: {e(score["engine"])}</h2>',
           f"<p>Freeze tag <code>{e(tag)}</code> · scored episodes {_n(score, 'n_scored')}</p>",
           "<table class=\"grid\"><thead><tr><th>Scenario</th><th>n</th><th>BLOCKED</th><th>ESCALATED</th>"
           "<th>NO DISCREPANCY FOUND</th><th>verdict matches expected</th></tr></thead><tbody>" + rows + "</tbody></table>",
           "<ul>",
           f"<li>Dangerous misses, primary definition: {_rate(score, 'dangerous_miss.primary')}</li>",
           f"<li>Dangerous misses, secondary definition: {_rate(score, 'dangerous_miss.secondary')}</li>",
           f"<li>False blocks on clean runs: {_rate(score, 'false_blocks')}</li>",
           (f"<li>INVALID episodes: {_n(score, 'invalid.k')} / {_n(score, 'invalid.n')} "
            f"(attempts {_n(score, 'invalid.attempts')}, invalid attempts {_n(score, 'invalid.invalid_attempts')})</li>")]
    if score.get("camera", {}).get("n"):
        out.append(f"<li>With-camera track blocked {_n(score, 'camera.with_camera_blocked')}, data-only track blocked "
                   f"{_n(score, 'camera.data_only_blocked')} of {_n(score, 'camera.n')}; camera added a block "
                   f"{_n(score, 'camera.camera_added_block')}, removed a block {_n(score, 'camera.camera_removed_block')} "
                   "(idealised camera (renders the simulator's true state))</li>")
    if "plan_set" in score:
        out.append(f"<li>Plan set: label matches {_n(score, 'plan_set.label_match')} / {_n(score, 'plan_set.n')}</li>")
    out.append("</ul>")
    out.append("<details><summary>Definitions (from the score file)</summary><ul>"
               + "".join(f"<li><strong>{e(k)}</strong>: {e(str(v))}</li>" for k, v in defs.items()) + "</ul></details>")
    out.append(seal_block(batch, sealed_hash, score))
    out.append("</section>")
    return "\n".join(out)


def seal_block(batch: str, sealed_hash: str, score: dict | None = None) -> str:
    cmd = (f"python -c \"import hashlib; print(hashlib.sha256(open('salt_{batch}','rb').read()"
           f" + open('manifest_{batch}.json','rb').read()).hexdigest())\"")
    same = f" (score file: {_n(score, 'seal_hash')})" if score else ""
    return (f'<p>Sealed hash, committed before the first scoring episode in <code>eval/sealed_hash_{html.escape(batch)}.txt</code>: '
            f'<code data-seal="{html.escape(batch)}">{html.escape(sealed_hash)}</code>{same}</p>'
            f"<p>Check it once the manifest and salt are published (sha256 of salt bytes then manifest bytes, as in "
            f"<code>eval/seal.py</code>); the output must equal the hash above:</p><pre>{html.escape(cmd)}</pre>")


def results_page(episodes: list[tuple[dict, str]], scores_dir: Path = RESULTS, seal_dir: Path = ROOT / "eval") -> str:
    parts = []
    for batch, tag in BATCHES:
        h = (seal_dir / f"sealed_hash_{batch}.txt").read_text(encoding="utf-8").strip()
        p = scores_dir / f"score_{batch}.json"
        if p.exists():
            parts.append(batch_section(batch, tag, json.loads(p.read_text(encoding="utf-8")), h))
        else:
            parts.append(f'<section class="batch" data-batch="{batch}"><h2>Batch {batch}</h2>'
                         f"<p>Freeze tags <code>{tag}</code>. Scoring in progress.</p>{seal_block(batch, h)}</section>")
    eps = "".join(f'<li><a href="index.html#/job/{html.escape(b["episode"])}">{html.escape(b["episode"])}</a>: '
                  f'{html.escape(what)}; recorded verdict {html.escape(str(b["result"]["verdict"]))}</li>' for b, what in episodes)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZeroState benchmark results</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="replay-banner" id="replay-banner">{BANNER}</div>
<header class="top"><strong>ZeroState</strong> <nav><a href="index.html#/">Episodes</a> <a href="results.html">Results</a></nav></header>
<main class="results">
<h1>Benchmark results</h1>
<p>Every number below is copied by <code>eval/tools/build_site_data.py</code> from the committed score files
(<code>eval/results/score_&lt;batch&gt;.json</code>). Operator actions and fault injection are by the test harness.</p>
{chr(10).join(parts)}
<h2>Episodes in this replay</h2>
<ul>{eps}</ul>
</main>
</body>
</html>
"""


def check_text(name: str, text: str) -> None:
    bad = hits(text)
    if bad:
        raise SystemExit(f"{name}: never-say hits {sorted(set(bad))}")
    if KEYLIKE.search(text):
        raise SystemExit(f"{name}: key-like string")


def build(out: Path = ROOT / "site", episodes=EPISODES, scores_dir: Path = RESULTS) -> dict[str, str]:
    """Writes out/ from scratch; returns {relative path: text}."""
    loaded = []
    for p, what in episodes:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            loaded.append((json.load(fh), what))
    texts = {k: json.dumps(v, ensure_ascii=False) for k, v in api_files([p for p, _ in episodes]).items()}
    texts.update(patched_ui())
    texts["results.html"] = results_page(loaded, scores_dir)
    for name, text in texts.items():
        check_text(name, text)
    if out.exists():
        shutil.rmtree(out)
    for name, text in texts.items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(text, encoding="utf-8", newline="\n")
    return texts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "site"))
    a = ap.parse_args()
    texts = build(Path(a.out))
    print(f"{a.out}: {len(texts)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
