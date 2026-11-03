"""Plan-check set: the generator is deterministic and every case's label matches what the rules return."""

import importlib.util
from pathlib import Path

import pytest

EVAL = Path(__file__).parents[1] / "eval"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


make_cases = load("make_cases", EVAL / "plan_cases" / "make_cases.py")
plan_benchmark = load("plan_benchmark", EVAL / "plan_benchmark.py")


def test_generator_is_deterministic(tmp_path):
    a = [p.read_bytes() for d in make_cases.write(tmp_path / "a", [7]) for p in sorted(d.iterdir())]
    b = [p.read_bytes() for d in make_cases.write(tmp_path / "b", [7]) for p in sorted(d.iterdir())]
    assert a == b


@pytest.mark.parametrize("case", list(make_cases.CASES))
def test_every_variant_matches_its_label(tmp_path, case):
    # every variant of the case, not just the one a seed picks
    seeds, seen = [], set()
    for s in range(200):
        if len(seen) == len(make_cases.CASES[case]):
            break
        v = make_cases.make(case, s)[2]["variant"]
        if v not in seen:
            seen.add(v)
            seeds.append(s)
    assert len(seen) == len(make_cases.CASES[case])
    make_cases.write(tmp_path, seeds)
    for d in sorted(tmp_path.glob(f"{case}_seed*")):
        r = plan_benchmark.run_case(d)
        assert r["label_match"], r
        assert r["blocked"] == bool(r["expected_fail"])
