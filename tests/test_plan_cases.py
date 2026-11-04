"""Plan-check set: the generator is deterministic and every case's label matches what the rules return."""

import importlib.util
import json
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



@pytest.fixture
def sealed2(tmp_path, monkeypatch):
    seal = plan_benchmark.runner.seal
    monkeypatch.setattr(seal, "ROOT", tmp_path)
    (tmp_path / "eval").mkdir()
    seal.seal("2", tmp_path / "sealed")
    monkeypatch.setattr(plan_benchmark.runner, "ROOT", tmp_path)
    calls = {("rev-parse", "HEAD"): (0, "abc"), ("diff", "--quiet", "HEAD"): (0, "")}
    monkeypatch.setattr(plan_benchmark.runner, "git", lambda *a: calls.get(a, (0, "abc")))
    return tmp_path, tmp_path / "sealed" / "manifest_2.json", tmp_path / "sealed" / "salt_2", calls


def test_sealed_plan_set_comes_from_the_manifest(sealed2, monkeypatch):
    root, m, s, _ = sealed2
    seen = []
    real = plan_benchmark.run_case

    def spy(d):  # every label exists before the first check runs
        seen.append(all((x / "label.json").exists() for x in (root / "cases").iterdir()) and len(list((root / "cases").iterdir())) == 45)
        return real(d)
    monkeypatch.setattr(plan_benchmark, "run_case", spy)
    res = plan_benchmark.run_sealed("2", m, s, root / "cases")
    entries = [e for e in json.loads(m.read_bytes())["entries"] if e["plant"] == "plan"]
    assert res["n"] == len(entries) == 45 and all(seen)
    assert sorted((r["case"], r["seed"]) for r in res["cases"]) == sorted((e["scenario"], e["seed"]) for e in entries)
    assert res["label_match"] == res["n"]


def test_sealed_plan_set_is_refused_like_the_runner(sealed2):
    root, m, s, calls = sealed2
    calls[("rev-parse", "HEAD")] = (0, "def")  # HEAD is not the tag
    with pytest.raises(SystemExit, match="is not bench-freeze-2"):
        plan_benchmark.run_sealed("2", m, s, root / "c1")
    calls[("rev-parse", "HEAD")] = (0, "abc")
    calls[("diff", "--quiet", "HEAD")] = (1, "")
    with pytest.raises(SystemExit, match="differ from the frozen tag"):
        plan_benchmark.run_sealed("2", m, s, root / "c2")
    calls[("diff", "--quiet", "HEAD")] = (0, "")
    (root / "eval" / "sealed_hash_2.txt").write_text("0" * 64)
    with pytest.raises(SystemExit, match="do not match"):
        plan_benchmark.run_sealed("2", m, s, root / "c3")
    assert not any((root / c).exists() for c in ("c1", "c2", "c3"))  # nothing generated when refused
