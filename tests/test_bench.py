"""Sealed benchmark tooling: seal, the runner's scoring checks and the batch loop, without the lab."""

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

EVAL = Path(__file__).parents[1] / "eval"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, EVAL / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seal, runner, bench = _load("seal"), _load("runner"), _load("run_benchmark")


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    monkeypatch.setattr(seal, "ROOT", tmp_path)
    (tmp_path / "eval").mkdir()
    h = seal.seal("p1", tmp_path / "sealed")
    return tmp_path, h


def test_seal_writes_hash_of_salt_and_manifest(sealed):
    root, h = sealed
    manifest, digest = seal.load(root / "sealed" / "manifest_p1.json", root / "sealed" / "salt_p1")
    assert digest == h == (root / "eval" / "sealed_hash_p1.txt").read_text().strip()
    entries = manifest["entries"]
    assert len(entries) == 65 and sum(e["scenario"] == "S0" for e in entries) == 15
    assert "S7" not in {e["scenario"] for e in entries}
    assert all(e["seed"] >= seal.MIN_SCORING_SEED for e in entries)
    assert len({e["seed"] for e in entries}) == 65


def test_seal_refuses_to_reseal(sealed):
    root, _ = sealed
    with pytest.raises(SystemExit):
        seal.seal("p1", root / "sealed")


def _scoring(monkeypatch, root, head="abc", tag=(0, "abc"), dirty=0):
    monkeypatch.setattr(runner, "ROOT", root)
    calls = {("rev-parse", "HEAD"): (0, head), ("diff", "--quiet", "HEAD"): (dirty, "")}
    monkeypatch.setattr(runner, "git", lambda *a: calls.get(a, tag))


def test_scoring_seed_runs_only_from_its_sealed_tag(sealed, monkeypatch):
    root, _ = sealed
    m, s = root / "sealed" / "manifest_p1.json", root / "sealed" / "salt_p1"
    e = json.loads(m.read_bytes())["entries"][0]
    _scoring(monkeypatch, root)
    assert runner.scoring_problem("p1", m, s, e["scenario"], e["seed"]) is None
    assert "needs --batch" in runner.scoring_problem(None, m, s, e["scenario"], e["seed"])
    assert "not in the sealed" in runner.scoring_problem("p1", m, s, e["scenario"], 12345678)
    _scoring(monkeypatch, root, head="def")
    assert "is not bench-freeze-p1" in runner.scoring_problem("p1", m, s, e["scenario"], e["seed"])
    _scoring(monkeypatch, root, tag=(128, ""))  # tag missing
    assert "is not bench-freeze-p1" in runner.scoring_problem("p1", m, s, e["scenario"], e["seed"])
    _scoring(monkeypatch, root, dirty=1)
    assert "differ from the frozen tag" in runner.scoring_problem("p1", m, s, e["scenario"], e["seed"])
    _scoring(monkeypatch, root)
    (root / "eval" / "sealed_hash_p1.txt").write_text("0" * 64)  # a manifest swapped after sealing
    assert "do not match" in runner.scoring_problem("p1", m, s, e["scenario"], e["seed"])


def test_fingerprint_ignores_line_endings_and_names_differences(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "x.py").write_bytes(b"x = 1\r\n")
    (tmp_path / "b" / "x.py").write_bytes(b"x = 1\n")
    fa = runner.fingerprint([("src/", str(tmp_path / "a"), "*.py")])
    assert fa == runner.fingerprint([("src/", str(tmp_path / "b"), "*.py")])
    (tmp_path / "b" / "x.py").write_bytes(b"x = 2\n")
    assert fa != runner.fingerprint([("src/", str(tmp_path / "b"), "*.py")])


# ---------------------------------------------------------------- batch loop
MANIFEST = {"entries": [{"plant": "p1", "scenario": s, "seed": 10000 + i} for i, s in enumerate(["S0", "S1", "S0"])]}
EVENING = datetime(2026, 11, 2, 23, 0)


def fake_run(results):
    calls = []

    def run(entry, a):
        calls.append(entry["seed"])
        r = results.pop(0)
        return None if r is None else {"valid": r, "match": True, "verdict": "X", "episode": f"ep{len(calls)}"}
    return run, calls


def test_batch_runs_all_and_resumes_without_repeats(tmp_path):
    p = tmp_path / "progress.jsonl"
    run, calls = fake_run([True, True])
    a = SimpleNamespace()
    assert bench.run_batch({"entries": MANIFEST["entries"][:2]}, p, a, run, lambda: EVENING) == 0
    run2, calls2 = fake_run([True])
    assert bench.run_batch(MANIFEST, p, a, run2, lambda: EVENING) == 0
    assert calls == [10000, 10001] and calls2 == [10002]


def test_invalid_is_retried_once_then_recorded(tmp_path):
    p = tmp_path / "progress.jsonl"
    run, calls = fake_run([False, False, True, True])
    assert bench.run_batch(MANIFEST, p, SimpleNamespace(), run, lambda: EVENING) == 0
    assert calls == [10000, 10000, 10001, 10002]
    s = bench.summary(MANIFEST, bench.read_progress(p))
    assert s["valid"] == 2 and s["invalid"] == 1 and s["invalid_rate"] == 0.5


def test_three_invalid_in_a_row_stops_and_resumes_later(tmp_path):
    p = tmp_path / "progress.jsonl"
    run, calls = fake_run([False, False, False])
    assert bench.run_batch(MANIFEST, p, SimpleNamespace(), run, lambda: EVENING) == 3
    assert calls == [10000, 10000, 10001]
    run2, calls2 = fake_run([True, True])  # lab fixed: S1's second try, then the last S0
    assert bench.run_batch(MANIFEST, p, SimpleNamespace(), run2, lambda: EVENING) == 0
    assert calls2 == [10001, 10002]


def test_refused_runner_stops_the_batch(tmp_path):
    run, _ = fake_run([None])
    assert bench.run_batch(MANIFEST, tmp_path / "p.jsonl", SimpleNamespace(), run, lambda: EVENING) == 2


def test_watchdog_skips_s0_beyond_ten_only_when_late():
    e = {"scenario": "S0"}
    five = datetime(2026, 11, 3, 5, 0)
    assert bench.watchdog_skip(e, five, remaining=40, mean_wall_s=420, s0_valid=10)  # 4 h 40 left: ends 09:40
    assert not bench.watchdog_skip(e, five, remaining=20, mean_wall_s=420, s0_valid=10)  # ends 07:20
    assert not bench.watchdog_skip(e, five, remaining=40, mean_wall_s=420, s0_valid=9)  # fewer than 10 S0 yet
    assert not bench.watchdog_skip({"scenario": "S1"}, five, remaining=40, mean_wall_s=420, s0_valid=12)
    assert not bench.watchdog_skip(e, datetime(2026, 11, 3, 1, 0), remaining=80, mean_wall_s=420, s0_valid=12)


def test_batch_2_is_the_full_engine_set(tmp_path, monkeypatch):
    monkeypatch.setattr(seal, "ROOT", tmp_path)
    (tmp_path / "eval").mkdir()
    seal.seal("2", tmp_path / "sealed")
    entries = json.loads((tmp_path / "sealed" / "manifest_2.json").read_bytes())["entries"]
    count = {}
    for e in entries:
        count[(e["plant"], e["scenario"])] = count.get((e["plant"], e["scenario"]), 0) + 1
    assert count[("p1", "S0")] == 15 and all(count[("p1", s)] == 5 for s in ("S7", "S7-same", "S13", "S8"))
    assert count[("plan", "PC0")] == 15 and all(count[("plan", f"PC{i}")] == 5 for i in range(1, 7))
    assert len(entries) == 45 + 35
