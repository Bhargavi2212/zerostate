"""Run the plan checks over generated plan-check cases (eval/plan_cases/make_cases.py) and compare with
the labels written before the run.

    python eval/plan_benchmark.py --cases <dir> [--out eval/results/plan_<date>.json]

Per case: BLOCKED or not, the rules that did not pass, and whether they equal the label exactly.
"""

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

import yaml

from zerostate.checks.plan import run_plan_checks
from zerostate.graph.build import merge
from zerostate.models.envelope import IsolationList
from zerostate.models.plant_map import PlantMap

ROOT = Path(__file__).parents[1]


def run_case(d: Path) -> dict:
    label = json.loads((d / "label.json").read_text(encoding="utf-8"))
    m = PlantMap.model_validate(yaml.safe_load((d / "plant_map.yaml").read_text(encoding="utf-8")))
    plan, problems = merge(m, IsolationList.model_validate(yaml.safe_load((d / "isolation_list.yaml").read_text(encoding="utf-8"))))
    if plan is None:  # a list that can't be merged never reaches a session
        return {**label, "merge_problems": problems, "blocked": True, "fired": [], "label_match": False}
    findings = run_plan_checks(plan, m, {})
    fired = sorted(f.rule_id for f in findings if f.status != "PASS")
    return {**label, "plan_hash": plan.content_hash(), "blocked": any(f.status == "FAIL" for f in findings),
            "fired": fired, "messages": [f"{f.rule_id}: {f.message}" for f in findings if f.status != "PASS"],
            "label_match": fired == label["expected_fail"]}


def run(cases: Path) -> dict:
    rows = [run_case(d) for d in sorted(p for p in cases.iterdir() if (p / "label.json").exists())]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    return {"date": date.today().isoformat(), "commit": commit, "n": len(rows),
            "label_match": sum(r["label_match"] for r in rows), "cases": rows}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / f"plan_{date.today().isoformat()}.json")
    a = ap.parse_args()
    res = run(a.cases)
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"{res['label_match']}/{res['n']} cases match their labels -> {a.out}")
