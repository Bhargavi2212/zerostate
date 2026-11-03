"""Copy the model-credit ledger out of the zerostate container and append a dated summary to
D:\\grfics\\credits_log.md (canonical, outside the repo). Run after each live session.

    python eval/tools/credits_report.py [--since 2026-11-03T00:00]
"""

import argparse
import json
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LOG = Path(r"D:\grfics\credits_log.md")


def summarise(lines: list[dict], since: str | None) -> dict:
    rows = [r for r in lines if not since or r["ts"] >= since]
    by = defaultdict(lambda: {"calls": 0, "usd": 0.0})
    for r in rows:
        k = f"{r['model']} / {r['purpose']}"
        by[k]["calls"] += 1
        by[k]["usd"] += r["usd"]
    return {"rows": len(rows), "usd": round(sum(r["usd"] for r in rows), 4),
            "total_usd": round(sum(r["usd"] for r in lines), 4), "by": dict(by)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="ISO time; only calls after it go into this entry")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        dst = Path(d) / "credits.jsonl"
        r = subprocess.run(["docker", "cp", "zerostate:/data/credits.jsonl", str(dst)], check=False,
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"no ledger in the container yet ({r.stderr.strip()[:120]})")
            return 1
        lines = [json.loads(x) for x in dst.read_text(encoding="utf-8").splitlines() if x.strip()]
    s = summarise(lines, a.since)
    entry = [f"\n## {datetime.now():%Y-%m-%d %H:%M} — ZeroState ledger{f' since {a.since}' if a.since else ''}",
             f"{s['rows']} calls, ${s['usd']:.4f} (ledger total ${s['total_usd']:.4f})"]
    entry += [f"- {k}: {v['calls']} calls, ${v['usd']:.4f}" for k, v in sorted(s["by"].items())]
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write("\n".join(entry) + "\n")
    print("\n".join(entry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
