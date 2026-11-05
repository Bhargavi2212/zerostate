"""Build site/ (Vercel root): the console from ui/ in recorded-replay mode + the results page, and one
Vercel function (api/model.py, from eval/tools/site_model.py) for the live Muse calls of "Check my isolation".

    python eval/tools/build_site_data.py [--out site]

Data: the real API in replay mode, in-process (FastAPI TestClient, no network), over the bundles in
EPISODES; every GET the console makes is saved as a JSON file under site/data/ (camera frames kept next to a
bundle are copied as data/sessions/<id>/frames/<sha256>.jpg). The results page is rendered only from
eval/results/score_<batch>.json. The function gets copies of the src/zerostate modules it imports (api/_zs/).
The build fails on any never-say hit or key-like string outside those copies.
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

BANNER = ("Recorded replay of benchmark and demo runs on simulated plants. Read-only: nothing here moves a plant. "
          "On Check my isolation, the Muse model calls are live.")
DEMO = "S8_seed503_20261104T125324"  # the nav link's session: feedback lied, camera frames kept
RESULTS = ROOT / "eval" / "results"
EPISODES = [  # (bundle, what it shows)
    (RESULTS / "bench/p1/S0_seed1184053442_20261103T071508/bundle.json.gz", "clean job (S0), batch p1"),
    (RESULTS / "bench/2/S8_seed1470975726_20261104T050105/bundle.json.gz",
     "feedback lied (S8), batch 2: the data-only and with-camera tracks both block"),
    (RESULTS / "bench/2/S7_seed1263244227_20261104T051135/bundle.json.gz", "a required step skipped / out of order (S7), batch 2"),
    (RESULTS / "bench/p2/S4-small_seed1013371090_20261104T102033/bundle.json.gz", "small passing valve on the P2 gas line (S4-small), batch p2"),
    (RESULTS / "demo" / DEMO / "bundle.json.gz",
     "demo run, tuning seed 503 (not a benchmark episode): feedback lied (S8), camera frames kept"),
    (RESULTS / "demo/S0_seed502_20261104T124516/bundle.json.gz",
     "demo run, tuning seed 502 (not a benchmark episode): clean job (S0), camera frames kept"),
]
BATCHES = [("p1", "bench-freeze-p1"), ("2", "bench-freeze-2"), ("p2", "bench-freeze-p2b and bench-freeze-p2c")]
KEYLIKE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|Bearer\s+\S+|MODEL_API_KEY\s*[=:]\s*\S+)")
UI_FILES = ["app.js", "lib.js", "job.js", "plant.js", "chart.js", "check.js", "style.css"]  # intake.js (import/confirm) is left out
VENDOR = ["__init__.py", "version.py", "wording.py", "api/voice.py", "llm/client.py", "llm/resolve.py", "llm/explain.py",
          "llm/prompts/resolve_request_v2.md", "llm/prompts/explain_v1.md"]  # under src/zerostate/, for api/model.py
REQUIREMENTS = "pydantic==2.14.2\n"  # the function's one dependency, pinned as in deploy/Dockerfile
VERCEL = {"functions": {"api/model.py": {"maxDuration": 60, "includeFiles": "{api/_zs/**,data/checks/**,data/sessions/*/detail.json}"}}}

# (file, regex, replacement): every pattern must match exactly once, so a ui/ change can't slip a control through
PATCHES = [
    ("app.js", r'import \{ intakeScreen \} from "\./intake\.js";\n', ""),
    ("app.js", r'    else if \(path === "/new"\) await intakeScreen\(app\);\n', ""),
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
    # check.js: a rehearsal (the shim's &steps=1) is a running session to the view; links to both modes
    ("check.js", r"const recorded = \[", "const recorded = !st.detail.rehearsal && (["),
    ("check.js", r"Date\.now\(\) / 1000 - last > 120;", "Date.now() / 1000 - last > 120);"),
    ("check.js", r'"Live session"', '"Rehearsal: your marks on a recorded session"'),
    ("check.js", r'(?<=You decide, and the issuer signs\."\),)',
     ('\n    el("p", { class: "small", id: "site-mode" }, "On this site the plant data is recorded (demo runs on the GRFICS simulator, '
     'tuning seeds; the operator actions in them are by the test harness). Your typed or spoken request, step commands and Why? '
     'go live to Muse Spark and Muse Voice Transcribe. ", ...[["S8_seed503_20261104T125324", "feedback lied (S8)"], ["S0_seed502_20261104T124516", "clean job (S0)"]].flatMap(([sid, what]) => '
     '[el("br"), `${what}: `, el("a", { href: `#/check?session=${sid}` }, "walk through the recorded checks"), " · ", '
     'el("a", { href: `#/check?session=${sid}&steps=1` }, "mark the steps yourself")])),')),
    ("check.js", r"through ZeroState's server; no browser speech service is used\.", "through this site's model function; no browser speech service is used."),
    ("check.js", r"Sign-off stays in the job screen, by a person\.", "Sign-off is done by a person in the lab console, never on this site."),
    ("check.js", r"waiting for verification by a second person \(console\) ", "the recording's second-person verification appears with this step's result "),
]

SHIM = r"""// Site only: maps the console's GET /api/... calls onto the recorded files under data/. Writes are refused, except:
// - the "Check my isolation" model calls (request matching, speech-to-text, Why?) go live to /api/model;
// - with #/check?...&steps=1 the visitor marks steps on a recorded session in this page only (a rehearsal: step k's
//   recorded findings appear a moment after the visitor marks k; nothing is stored or sent anywhere).
// The event stream becomes a recorded event list (data/sessions/<id>/stream.json), played at ?speed=N if given.
(() => {
  const realFetch = window.fetch.bind(window);
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const REVEAL_MS = 2500;
  const rehearsing = () => new URLSearchParams(location.hash.split("?")[1] || "").get("steps") === "1";
  const marks = {}; // session id -> {k: {by, t}}, this page only
  const streams = new Set();
  function file(path) {
    let m;
    if (path === "/api/sessions") return "data/sessions.json";
    if (path === "/api/checks/plans") return "data/checks/plans.json";
    if ((m = path.match(/^\/api\/plants\/([\w-]+)\/map$/))) return `data/plants/${m[1]}/map.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/camera\/(\d+)$/))) return `data/sessions/${m[1]}/camera/${m[2]}.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/stream(\?.*)?$/))) return `data/sessions/${m[1]}/stream.json`;
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)$/))) return `data/sessions/${m[1]}/detail.json`;
    return null;
  }
  // the recorded session as it stands after the visitor's marks: later steps unmarked, their findings and the
  // verdict held back until the visitor reaches the last step the recording evaluated
  function rehearsal(d) {
    const mine = marks[d.id] || {}, now = Date.now();
    const evaluated = Math.max(0, ...d.findings.filter((f) => f.step !== null && f.step !== undefined).map((f) => f.step));
    const shown = Math.max(0, ...Object.entries(mine).filter(([, m]) => now - m.t >= REVEAL_MS).map(([k]) => Number(k)));
    const out = { ...d, state: "running", signature: null };
    out.steps = d.steps.map((s) => {
      const m = mine[s.k], seen = m && s.k <= shown;
      return { ...s, marked_by: m ? m.by : null, marked_t: m ? m.t / 1000 : null, result: seen ? s.result : null,
        verified_by: seen ? s.verified_by : null, verified_t: seen ? s.verified_t : null, finding_ids: seen ? s.finding_ids : [] };
    });
    out.findings = d.findings.filter((f) => (f.step === null || f.step === undefined ? shown >= evaluated : f.step <= shown));
    if (shown < evaluated) {
      out.verdict = null; out.verdict_with_camera = null;
      out.tracks = Object.fromEntries(Object.entries(d.tracks || {}).map(([k, t]) => [k, t && { ...t, verdict: null, reasons: [] }]));
    }
    out.rehearsal = { evaluated, shown };
    return out;
  }
  async function detail(sid) {
    const d = await (await realFetch(`data/sessions/${sid}/detail.json`)).json();
    return rehearsing() ? rehearsal(d) : d;
  }
  async function mark(sid, k, by) {
    const d = rehearsal(await (await realFetch(`data/sessions/${sid}/detail.json`)).json());
    const next = d.steps.find((s) => s.kind !== "final" && !s.marked_by);
    if (!by) return json(400, { error: "bad_input", detail: "type your name first" });
    if (!next || next.k !== k) return json(409, { error: "conflict", detail: next ? `mark step ${next.k} first` : "every step is marked" });
    if (k > d.rehearsal.evaluated) return json(409, { error: "conflict", detail: `the recording stops before step ${k}` });
    (marks[sid] = marks[sid] || {})[k] = { by, t: Date.now() };
    setTimeout(() => { for (const s of streams) if (!s.closed && s.sid === sid) s.emit("finding", "{}"); }, REVEAL_MS + 50);
    return json(200, { queued: true, k, by });
  }
  const model = (body) => realFetch("/api/model", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  window.fetch = async (path, init = {}) => {
    if (typeof path !== "string" || !path.startsWith("/api/")) return realFetch(path, init);
    let m;
    const method = (init.method || "GET").toUpperCase();
    if (method !== "GET") {
      const body = init.body ? JSON.parse(init.body) : {};
      if (path === "/api/checks/resolve") return model({ op: "resolve", ...body });
      if (path === "/api/voice/command") {
        const d = body.session ? await detail(body.session).catch(() => null) : null;
        return model({ op: "voice", ...body, detail: d && { plan: d.plan, steps: d.steps, verdict: d.verdict, verdict_with_camera: d.verdict_with_camera, tracks: d.tracks } });
      }
      if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/explain$/))) return model({ op: "explain", session: m[1], question: body.question });
      if ((m = path.match(/^\/api\/sessions\/([\w-]+)\/steps\/(\d+)\/done$/)) && rehearsing()) return mark(m[1], Number(m[2]), String(body.by || "").trim());
      return json(409, { error: "replay", detail: "recorded replay: read-only" });
    }
    if ((m = path.match(/^\/api\/sessions\/([\w-]+)$/))) return json(200, await detail(m[1]));
    const f = file(path);
    return f ? realFetch(f) : json(404, { error: "not_found", detail: "not in this recorded replay" });
  };
  class RecordedEvents {
    constructor(url) {
      this.listeners = {}; this.onerror = null; this.closed = false;
      this.sid = (url.match(/^\/api\/sessions\/([\w-]+)\/stream/) || [])[1];
      streams.add(this);
      const speed = Number(new URL(url, location.href).searchParams.get("speed")) || 0;
      window.fetch(url).then((r) => r.json()).then(async (list) => {
        let prev = null;
        for (const e of list) {
          const t = JSON.parse(e.data).t;
          if (speed && prev !== null && typeof t === "number") await new Promise((ok) => setTimeout(ok, Math.max(0, (t - prev) * 1000 / speed)));
          if (typeof t === "number") prev = t;
          if (this.closed) return;
          this.emit(e.event, e.data);
        }
        if (!this.closed && this.onerror && !rehearsing()) this.onerror(); // a rehearsal stays open for the visitor's marks
      });
    }
    emit(kind, data) { for (const fn of this.listeners[kind] || []) fn({ data }); }
    addEventListener(kind, fn) { (this.listeners[kind] = this.listeners[kind] || []).push(fn); }
    close() { this.closed = true; streams.delete(this); }
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


def api_files(bundles: list[Path], frames: dict[str, bytes] | None = None) -> dict[str, object]:
    """{relative path under site/: JSON value} from the real API in replay mode; kept camera frames go into
    `frames` ({relative path: bytes}) and the camera files point at them."""
    from fastapi.testclient import TestClient

    from zerostate.api import server

    out: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for b in bundles:
            (tmp / "bundles" / b.parent.name).mkdir(parents=True)
            shutil.copy(b, tmp / "bundles" / b.parent.name / b.name)
            if (b.parent / "frames").is_dir():
                shutil.copytree(b.parent / "frames", tmp / "bundles" / b.parent.name / "frames")
        client = TestClient(server.create_app(tmp, tmp / "audit.sqlite", tmp, {}, replay_dir=tmp / "bundles"))
        sessions = _get(client, "/api/sessions").json()
        out["data/sessions.json"] = sessions
        out["data/checks/plans.json"] = _get(client, "/api/checks/plans").json()
        for s in sessions:
            sid = s["id"]
            d = _get(client, f"/api/sessions/{sid}").json()
            out[f"data/sessions/{sid}/detail.json"] = d
            out[f"data/plants/{d['plant']}/map.json"] = _get(client, f"/api/plants/{d['plant']}/map").json()
            out[f"data/sessions/{sid}/stream.json"] = _sse(_get(client, f"/api/sessions/{sid}/stream").text)
            for eid in sorted({f["eval_id"] for f in d["findings"] if f["source"] == "camera"}):
                cam = _get(client, f"/api/sessions/{sid}/camera/{eid}").json()
                for r in cam["readings"]:
                    if r["frame_url"]:  # an <img> loads it, not fetch: point it at the copied file
                        name = f"data/sessions/{sid}/frames/{r['frame_sha256']}.jpg"
                        if frames is not None:
                            frames[name] = _get(client, r["frame_url"]).content
                        r["frame_url"], r["crop_url"] = name, None
                out[f"data/sessions/{sid}/camera/{eid}.json"] = cam
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
                     ('<nav><a href="#/">Sessions</a> <a href="#/new">New isolation</a> <a href="#/check">Check my isolation</a></nav>', NAV),
                     ('<script type="module" src="app.js">', '<script src="replay.js"></script>\n<script type="module" src="app.js">')]:
        if page.count(old) != 1:
            raise SystemExit(f"site patch for index.html: {old!r} not found once")
        page = page.replace(old, new)
    files["index.html"], files["replay.js"] = page, SHIM
    files["api/model.py"] = (ROOT / "eval" / "tools" / "site_model.py").read_text(encoding="utf-8")
    for name in VENDOR:
        files[f"api/_zs/zerostate/{name}"] = (ROOT / "src" / "zerostate" / name).read_text(encoding="utf-8")
    for pkg in ("api", "llm"):
        files[f"api/_zs/zerostate/{pkg}/__init__.py"] = ""
    files["requirements.txt"], files["vercel.json"] = REQUIREMENTS, json.dumps(VERCEL, indent=1) + "\n"
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
<header class="top"><strong>ZeroState</strong> {NAV}</header>
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


NAV = (f'<nav><a href="index.html#/">Episodes</a> <a href="index.html#/check?session={DEMO}">Check my isolation</a> '
       '<a href="results.html">Results</a></nav>')


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
    frames: dict[str, bytes] = {}
    texts = {k: json.dumps(v, ensure_ascii=False) for k, v in api_files([p for p, _ in episodes], frames).items()}
    texts.update(patched_ui())
    texts["results.html"] = results_page(loaded, scores_dir)
    for name, text in texts.items():
        if not name.startswith("api/_zs/"):  # copies of src/ (the never-say list itself, the key header line)
            check_text(name, text)
    if out.exists():
        shutil.rmtree(out)
    for name, text in texts.items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(text, encoding="utf-8", newline="\n")
    for name, raw in frames.items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(raw)
    return {**texts, **frames}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "site"))
    a = ap.parse_args()
    texts = build(Path(a.out))
    print(f"{a.out}: {len(texts)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
