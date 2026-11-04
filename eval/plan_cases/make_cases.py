"""Plan-check set (C3): PC0 is the correct P2 isolation list; PC1-PC6 each plant one known plan error in
a copy of it (or of the P2 map). Each case's label (the plan rules expected to FAIL) is written with the
case, before any check runs. The seed picks the point or variant.

    python eval/plan_cases/make_cases.py --out <dir> --seeds 1 2 3

writes <dir>/PC<n>_seed<s>/{plant_map.yaml, isolation_list.yaml, label.json}. Generated cases are not
committed; scoring seeds come from the sealed manifest.
"""

import argparse
import copy
import json
import random
from pathlib import Path

import yaml

P2 = Path(__file__).parents[2] / "plants" / "p2_gasline"


def drop_points(*tags):
    def f(m, lst):
        lst["points"] = [p for p in lst["points"] if p["tag"] not in tags]
    return f


def work_on(tag):
    def f(m, lst):
        lst["work_equipment"] = tag
    return f


def remove_relief(m, lst):
    m["nodes"] = [n for n in m["nodes"] if n["id"] != "PSV-214"]
    m["pipes"] = [p for p in m["pipes"] if "PSV-214" not in (p["a"], p["b"])]


def control_valve(tag):
    def f(m, lst):
        n = next(n for n in m["nodes"] if n["id"] == tag)
        n.update(device="control_valve", actuation="actuated")
    return f


def wrong_tag(m, lst):  # the adjacent line's block, written everywhere the right one was
    for p in lst["points"]:
        p["tag"] = "XV-231" if p["tag"] == "XV-204" else p["tag"]
    for pr in lst["proving"]:
        pr["proves"] = ["XV-231" if t == "XV-204" else t for t in pr["proves"]]


def drop_proving(tag):
    def f(m, lst):
        lst["proving"] = [pr for pr in lst["proving"] if pr["tag"] != tag]
    return f


def bleed_into_header(m, lst):
    next(n for n in m["nodes"] if n["id"] == "BV-202")["discharges_to"] = "header:D-220"


# case -> [(variant, mutation, expected FAIL rule ids)]. XV-201/XV-203 are a double block: dropping one
# still leaves a block between S-200 and F-210, so PC1 drops XV-204 or both upstream blocks.
CASES = {
    "PC0": [("correct", lambda m, lst: None, [])],
    "PC1": [("drop XV-204", drop_points("XV-204"), ["PLAN-PATHS"]),
            ("drop XV-201 and XV-203", drop_points("XV-201", "XV-203"), ["PLAN-PATHS"])],
    "PC2": [("work on XV-201", work_on("XV-201"), ["PLAN-LIVESIDE", "PLAN-PATHS"]),
            ("work on XV-203", work_on("XV-203"), ["PLAN-LIVESIDE"]),
            ("work on XV-204", work_on("XV-204"), ["PLAN-LIVESIDE", "PLAN-PATHS"])],
    "PC3": [("heater E-215, PSV-214 removed", remove_relief, ["PLAN-BOXEDIN"])],
    "PC4": [(f"{t} an actuated control valve", control_valve(t), ["PLAN-SOFTWARE"]) for t in ("XV-201", "XV-203", "XV-204")],
    "PC5": [("XV-231 instead of XV-204", wrong_tag, ["PLAN-PATHS"])],
    "PC6": [("no proving point for XV-204", drop_proving("VV-213"), ["PLAN-PROVING"]),
            ("no proving point for XV-201/XV-203", drop_proving("BV-202"), ["PLAN-PROVING"]),
            ("BV-202 bleeds into header D-220", bleed_into_header, ["PLAN-PROVING"])],
}


def make(case: str, seed: int) -> tuple[dict, dict, dict]:
    """(map, list, label) for one case and seed; deterministic."""
    variant, mutate, expected = random.Random(f"{case}:{seed}").choice(CASES[case])
    m = copy.deepcopy(yaml.safe_load((P2 / "plant_map.yaml").read_text(encoding="utf-8")))
    lst = copy.deepcopy(yaml.safe_load((P2 / "isolation_list.yaml").read_text(encoding="utf-8")))
    mutate(m, lst)
    return m, lst, {"case": case, "seed": seed, "variant": variant, "expected_fail": sorted(expected)}


def write_one(out: Path, case: str, seed: int) -> Path:
    m, lst, label = make(case, seed)
    d = out / f"{case}_seed{seed}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "label.json").write_text(json.dumps(label, indent=1), encoding="utf-8")  # label first
    (d / "plant_map.yaml").write_text(yaml.safe_dump(m, sort_keys=False), encoding="utf-8")
    (d / "isolation_list.yaml").write_text(yaml.safe_dump(lst, sort_keys=False), encoding="utf-8")
    return d


def write(out: Path, seeds: list[int]) -> list[Path]:
    return [write_one(out, case, seed) for seed in seeds for case in CASES]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--seeds", required=True, type=int, nargs="+")
    a = ap.parse_args()
    print(f"{len(write(a.out, a.seeds))} cases in {a.out}")
