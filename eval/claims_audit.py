"""Claims audit: every claim in eval/claims.yaml is PASSING or NOT PASSING, from tests and committed results.

    python eval/claims_audit.py [--claims eval/claims.yaml] [--readme README.md]

A claim is NOT PASSING on a missing or failing test (xfail counts as failing: --runxfail), a missing
result file or key, an unmet `require`, `tags_same_commit` tags on different commits, a `src_diff` whose
`src/` changes between two tags are not exactly the files listed (none listed: identical), or a README that
carries a different version of its sentence. A claim absent from the README is reported "not in README".
Exit 1 if any claim the README uses is NOT PASSING, or if this output has a never-say word.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from zerostate.wording import hits

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\{([\w.\-]+)(?::([^{}]+))?\}")


def lookup(data, key: str):
    for part in key.split("."):
        data = data[part]
    return data


def norm(text: str) -> str:
    return " ".join(text.split())


def anchor(sentence: str) -> str:
    """The longest fixed stretch of a sentence: finds the README's version of it whatever the numbers."""
    return max((norm(s) for s in re.split(r"\{[^{}]+\}", sentence)), key=len)


def pytest_rc(tests: tuple[str, ...], root: Path) -> int:
    cmd = [sys.executable, "-m", "pytest", "-q", "--runxfail", "-p", "no:cacheprovider", *tests]
    return subprocess.run(cmd, cwd=root, capture_output=True, check=False).returncode


def git_commit(tag: str, root: Path) -> str | None:
    r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}"], cwd=root,
                       capture_output=True, text=True, check=False)
    return r.stdout.strip() or None


def git_src_changes(a: str, b: str, root: Path) -> list[str] | None:
    r = subprocess.run(["git", "diff", "--name-only", f"{a}^{{commit}}", f"{b}^{{commit}}", "--", "src/"], cwd=root,
                       capture_output=True, text=True, check=False)
    return sorted(r.stdout.split()) if r.returncode == 0 else None


def audit_claim(c: dict, root: Path, readme: str, run=pytest_rc, commit=git_commit, src_changes=git_src_changes) -> dict:
    why, tests = [], tuple(c.get("tests") or ())
    missing = [t for t in tests if not (root / t.split("::")[0]).exists()]
    why += [f"missing test {t}" for t in missing]
    if tests and not missing and (rc := run(tests, root)) != 0:
        why.append(f"tests not passing (pytest exit {rc})")
    data = None
    if c.get("results"):
        found = sorted(root.glob(c["results"]))
        if not found:
            why.append(f"missing result file {c['results']}")
        else:
            data = json.loads(found[-1].read_text(encoding="utf-8"))
    keys = list(c.get("keys") or [])
    why += [f"placeholder {k} not in keys" for k, _ in PLACEHOLDER.findall(c["sentence"]) if k not in keys]
    values = {}
    for k in keys if data is not None else []:  # no file: already reported once
        try:
            values[k] = lookup(data, k)
        except (KeyError, TypeError, IndexError):
            why.append(f"missing key {k}")
    for k, want in (c.get("require") or {}).items():
        if k in values and values[k] != want:
            why.append(f"{k} is {values[k]!r}, claim needs {want!r}")
    tags = c.get("tags_same_commit") or []
    commits = [commit(t, root) for t in tags]
    why += [f"missing tag {t}" for t, h in zip(tags, commits) if h is None]
    if None not in commits and len(set(commits)) > 1:
        why.append(f"tags on different commits: {', '.join(tags)}")
    for d in c.get("src_diff") or []:
        got = src_changes(d["from"], d["to"], root)
        if got is None:
            why.append(f"cannot diff src/ {d['from']}..{d['to']}")
        elif got != sorted(d.get("files") or []):
            why.append(f"src/ changes {d['from']}..{d['to']} are {got or 'none'}, claim lists {sorted(d.get('files') or []) or 'none'}")
    rendered = None
    if all(k in values for k, _ in PLACEHOLDER.findall(c["sentence"])):
        rendered = norm(PLACEHOLDER.sub(lambda m: format(values[m[1]], m[2] or ""), c["sentence"]))
    text = norm(readme)
    used = bool(text) and anchor(c["sentence"]) in text
    if used and (rendered is None or rendered not in text):
        why.append("README sentence differs from the rendered one")
    return {"id": c["id"], "batch": str(c["batch"]), "engine": c["engine"], "passing": not why,
            "used": used, "why": why, "rendered": rendered}


def report(results: list[dict]) -> str:
    out = []
    for r in results:
        where = "in README" if r["used"] else "not in README"
        out.append(f"{r['id']:<7} {'PASSING' if r['passing'] else 'NOT PASSING':<11}  "
                   f"[batch {r['batch']}: {r['engine']}] {where}")
        out += [f"          - {w}" for w in r["why"]]
        if r["passing"]:
            out.append(f"          {r['rendered']}")
    return "\n".join(out)


def main(argv=None, run=pytest_rc, commit=git_commit) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--claims", type=Path, default=None)
    ap.add_argument("--readme", type=Path, default=None)
    a = ap.parse_args(argv)
    claims = yaml.safe_load((a.claims or a.root / "eval" / "claims.yaml").read_text(encoding="utf-8"))["claims"]
    readme_path = a.readme or a.root / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    results = [audit_claim(c, a.root, readme, run, commit) for c in claims]
    out = report(results)
    print(out)
    if bad := hits(out):
        print(f"never-say words in this output: {bad}")
        return 1
    return 1 if any(r["used"] and not r["passing"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
