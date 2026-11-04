"""Run the plan checks over generated plan-check cases (eval/plan_cases/make_cases.py) and compare with
the labels written before the run.

    python eval/plan_benchmark.py --cases <dir> [--out eval/results/plan_<date>.json]
    python eval/plan_benchmark.py --batch 2 --manifest D:/grfics/sealed/manifest_2.json --salt D:/grfics/sealed/salt_2

Sealed (--batch): the cases are generated from the manifest's plan entries (PC0-PC6 seeds), every label
written before any check runs, and the run is refused like the runner refuses a scoring seed (manifest
and salt match the committed hash, the entry is in the manifest, HEAD = bench-freeze-<batch>, clean tree).
Per case: BLOCKED or not, the rules that did not pass, and whether they equal the label exactly.
"""

import argparse
import importlib.util
import json
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import yaml

from zerostate.checks.plan import run_plan_checks
from zerostate.graph.build import merge
from zerostate.models.envelope import IsolationList
from zerostate.models.plant_map import PlantMap

ROOT = Path(__file__).parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load("runner", ROOT / "eval" / "runner.py")
make_cases = _load("make_cases", ROOT / "eval" / "plan_cases" / "make_cases.py")


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


def run_sealed(batch: str, manifest_p, salt_p, cases: Path) -> dict:
    """The sealed plan set: refused (SystemExit) unless every entry passes the runner's scoring checks;
    all cases and labels are written before the first check runs."""
    manifest, _ = runner.seal.load(manifest_p, salt_p)
    entries = [e for e in manifest["entries"] if e["plant"] == "plan"]
    if not entries:
        raise SystemExit(f"no plan entries in the sealed {batch} manifest")
    for e in entries:
        if problem := runner.scoring_problem(batch, manifest_p, salt_p, e["scenario"], e["seed"], plant="plan"):
            raise SystemExit(problem)
    for e in entries:  # labels first, for every case
        make_cases.write_one(cases, e["scenario"], e["seed"])
    return {**run(cases), "batch": batch, "sealed_hash": runner.seal.load(manifest_p, salt_p)[1]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, help="unsealed: run over an existing case directory")
    ap.add_argument("--batch", help="sealed batch holding the plan set, e.g. 2")
    ap.add_argument("--manifest", help="sealed manifest, kept outside the repo")
    ap.add_argument("--salt", help="sealed salt, kept outside the repo")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.batch:
        if not (a.manifest and a.salt):
            ap.error("--batch needs --manifest and --salt")
        res = run_sealed(a.batch, a.manifest, a.salt, a.cases or Path(tempfile.mkdtemp(prefix=f"plan_{a.batch}_")))
        a.out = a.out or ROOT / "eval" / "results" / "bench" / a.batch / "plan.json"
        a.out.parent.mkdir(parents=True, exist_ok=True)
    elif a.cases:
        res = run(a.cases)
        a.out = a.out or ROOT / "eval" / "results" / f"plan_{date.today().isoformat()}.json"
    else:
        ap.error("give --cases, or --batch with --manifest and --salt")
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"{res['label_match']}/{res['n']} cases match their labels -> {a.out}")
