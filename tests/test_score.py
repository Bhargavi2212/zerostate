"""eval/score.py on a fixture seal (never the real one) and episode folders built from committed p1
episodes: each hazard definition, each window, Wilson CIs, a refused hash, INVALID entries."""

import gzip
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BENCH = ROOT / "eval" / "results" / "bench" / "p1"
spec = importlib.util.spec_from_file_location("score", ROOT / "eval" / "score.py")
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)

CLEAN_PASS = "S0_seed1184053442_20261103T071508"
BLOCKED_CLEAN_TRUTH = "S1_seed1018302062_20261103T030057"  # gauge frozen during the vent; valves really closed
LEAK_BLOCKED = "S4-small_seed1318434843_20261103T035803"
S1B_FLOW = "S1b_seed233000811_20261103T054504"
FS = score.P1_FULL_SCALE


def _episode(name: str) -> Path:
    hits = [p for p in BENCH.iterdir() if p.name.startswith(name.split("_2026")[0] + "_")]
    assert hits, name
    return hits[0]


def _copy(name: str, dest: Path, new_name: str) -> Path:
    d = dest / new_name
    shutil.copytree(_episode(name), d)
    return d


def _seal(tmp: Path, entries: list[dict], batch: str = "p1") -> tuple[Path, Path, Path]:
    manifest = json.dumps({"batch": batch, "entries": entries}, indent=1).encode()
    (tmp / "manifest.json").write_bytes(manifest)
    (tmp / "salt").write_bytes(b"fixture-salt")
    (tmp / "hash.txt").write_text(score.seal.digest(b"fixture-salt", manifest) + "\n", encoding="utf-8")
    return tmp / "manifest.json", tmp / "salt", tmp / "hash.txt"


def _rewrite_truth(d: Path, edit) -> None:
    with gzip.open(d / "truth.jsonl.gz", "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    rows = [edit(r) for r in rows]
    with gzip.open(d / "truth.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)


@pytest.fixture(scope="module")
def batch(tmp_path_factory):
    """Four episodes: clean pass, clean truth but BLOCKED (false block), a leak passed (truth edited: f1 at
    0.5 % of full scale after the verdict: a dangerous miss under the secondary definition only), a leak
    blocked. Plus a manifest entry whose only episode has a tampered audit row (INVALID)."""
    tmp = tmp_path_factory.mktemp("score")
    res = tmp / "bench"
    res.mkdir()
    _copy(CLEAN_PASS, res, CLEAN_PASS)
    blocked = _copy(BLOCKED_CLEAN_TRUTH, res, BLOCKED_CLEAN_TRUTH)
    meta = json.loads((blocked / "meta.json").read_text(encoding="utf-8"))
    meta["scenario"] = {**meta["scenario"], "id": "S0", "faults": []}
    meta["faults"] = []
    (blocked / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (blocked / "events.jsonl").unlink(missing_ok=True)

    leak = _copy(CLEAN_PASS, res, "S4-small_seed12345_fixture")
    ep = score.load_episode(leak)
    vt = score.verdict_time(ep)
    meta = json.loads((leak / "meta.json").read_text(encoding="utf-8"))
    meta["scenario"] = {**meta["scenario"], "id": "S4-small", "faults": [{"set": {"f1_leak_pct": [0.3, 1.5]}}]}
    meta["faults"] = [{"set": {"f1_leak_pct": 0.8}}]
    meta["seed"] = 12345
    (leak / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    t_fault = ep["truth"][0]["t"]  # the leak is present from the start: its fault event, as the runner logs it
    (leak / "events.jsonl").write_text(json.dumps({"t": t_fault, "kind": "fault", "data": {"set": {"f1_leak_pct": 0.8}}}) + "\n",
                                       encoding="utf-8")

    def leak_after_verdict(r):
        if r["t"] >= vt:
            r["outputs"]["f1_flow"] = 5.0  # 0.5 % of 1000
        return r
    _rewrite_truth(leak, leak_after_verdict)
    _copy(LEAK_BLOCKED, res, LEAK_BLOCKED)

    bad = _copy(CLEAN_PASS, res, "S0_seed777_fixture")
    audit = json.loads((bad / "audit_export.json").read_text(encoding="utf-8"))
    audit[3]["payload"]["k"] = 9  # an edited row no longer matches its hash
    (bad / "audit_export.json").write_text(json.dumps(audit), encoding="utf-8")
    meta = json.loads((bad / "meta.json").read_text(encoding="utf-8"))
    meta["seed"] = 777
    (bad / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def seed(name):
        return int(name.split("_seed")[1].split("_")[0])
    entries = [{"plant": "p1", "scenario": "S0", "seed": seed(CLEAN_PASS)},
               {"plant": "p1", "scenario": "S0", "seed": seed(BLOCKED_CLEAN_TRUTH)},
               {"plant": "p1", "scenario": "S4-small", "seed": 12345},
               {"plant": "p1", "scenario": "S4-small", "seed": seed(LEAK_BLOCKED)},
               {"plant": "p1", "scenario": "S0", "seed": 777}]
    m, s, h = _seal(tmp, entries)
    return score.score("p1", m, s, res, hash_p=h, muse_results=tmp / "none.json"), tmp


def test_full_scale_comes_from_the_committed_map_and_equals_the_pins():
    assert score.full_scale("p1_grfics") == {"f1": 1000, "f2": 500, "purge": 2000, "product": 500}
    with pytest.raises(SystemExit):
        score.full_scale("p2_gasline")


def test_wilson_values():
    assert score.wilson(0, 15) == (0.0, 0.2039)  # z^2 / (n + z^2)
    assert score.wilson(5, 10) == (0.2366, 0.7634)
    assert score.wilson(0, 0) == (None, None)
    assert "upper bound ≈ 3/n = 0.20" in score.show(score.rate(0, 15))


def test_hash_mismatch_is_refused(tmp_path):
    m, s, h = _seal(tmp_path, [{"plant": "p1", "scenario": "S0", "seed": 10001}])
    h.write_text("0" * 64, encoding="utf-8")
    with pytest.raises(SystemExit, match="refused"):
        score.score("p1", m, s, tmp_path, hash_p=h)


def test_wrong_batch_manifest_is_refused(tmp_path):
    m, s, h = _seal(tmp_path, [], batch="2")
    with pytest.raises(SystemExit, match="refused"):
        score.score("p1", m, s, tmp_path, hash_p=h)


def test_a_scenario_fault_that_never_fired_leaves_the_episode_clean():
    """Batch p1 S1 seed 260352266: blocked at step 1 (slow mode switch) before the fault's time. Truth: clean,
    so its block is a false block, not an INVALID episode (DECISIONS Nov 3)."""
    ep = score.load_episode(_episode("S1_seed260352266_20261103T030055"))
    assert ep["fault_t"] is None and not score.faulty(ep)
    r = score.score_episode(ep, FS)
    assert r["label"]["primary"] == "clean" and r["verdict"] == "BLOCKED"
    assert r["note"].startswith("fault never injected")


def test_batch_keys_and_counts(batch):
    s, _ = batch
    assert s["dangerous_miss"]["primary"]["k"] == 0 and s["dangerous_miss"]["primary"]["n"] == 4
    assert s["dangerous_miss"]["secondary"]["k"] == 1  # the passed 0.5 % leak, under 0.1 % only
    assert set(s["dangerous_miss"]["secondary"]) == {"k", "n", "ci_low", "ci_high", "ci_high_pct"}
    assert s["false_blocks"]["k"] == 1 and s["false_blocks"]["n"] == 2
    assert (s["false_blocks"]["blocked"], s["false_blocks"]["escalated"]) == (1, 0)
    assert s["decided_on"]["k"] == s["decided_on"]["n"] == 4
    for b in s["baselines"].values():
        assert b["decided_on"]["n"] == 4 and b["decided_on"]["whole_job"] <= b["decided_on"]["k"]

    assert s["missed_faults"] == {"k": 1, "n": 2}  # the leak passed: no primary condition met
    assert s["missed_faults_secondary"] == {"k": 0, "n": 2}
    assert s["invalid"]["k"] == 1 and s["invalid"]["n"] == 5
    assert "S0_seed777_fixture" in s["episode_problems"]
    assert any("does not match its hash" in p for p in s["episode_problems"]["S0_seed777_fixture"])
    assert s["per_scenario"]["S0"] == {"n": 2, "blocked": 1, "escalated": 0, "no_discrepancy": 1, "match": 2,
                                       "notes": s["per_scenario"]["S0"]["notes"]}
    assert {"with_camera_blocked", "n"} <= set(s["camera"]) and s["camera"]["n"] == 0
    assert s["engine"] == "live checks only (Phase 1 engine)"


def test_labels_per_definition(batch):
    s, _ = batch
    rows = {r["episode"]: r for r in s["episodes"]}
    assert rows[CLEAN_PASS]["label"] == {"primary": "clean", "secondary": "clean"}
    assert rows["S4-small_seed12345_fixture"]["label"] == {"primary": "fault, below hazard limits", "secondary": "unsafe"}
    assert rows[LEAK_BLOCKED]["label"]["secondary"] == "unsafe"
    assert rows[LEAK_BLOCKED]["time_to_block_process_s"] > 0
    assert rows["S4-small_seed12345_fixture"]["severity_at_release"]["max_isolated_flow_pct"] == 0.5


def test_s1b_mismatch_note():
    ep = score.load_episode(_episode(S1B_FLOW))
    r = score.score_episode(ep, FS)
    assert r["match"] is False
    assert r["note"].startswith("caught by flow before the hold")
    assert "1.461 %" in r["note"] and "f1_flow = 10.1" in r["note"]


def _toy(rows, verdict="NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF", marks=None):
    steps = [{"k": 2, "kind": "isolate", "targets": ["f1", "purge"], "required_state": 0, "settle_process_s": 60},
             {"k": 5, "kind": "vent_open", "target": "purge", "required_state": 100},
             {"k": 6, "kind": "vent_close", "target": "purge", "required_state": 0, "settle_process_s": 60},
             {"k": 7, "kind": "hold"}, {"k": 8, "kind": "final"}]
    full = {"pressure": 100.0, "f1_flow": 0, "f2_flow": 0, "purge_flow": 0, "product_flow": 0}
    truth = [{"t": t, "outputs": {**full, **o}, "state": {"f1_valve_pos": 0, "purge_valve_pos": 0, **st}} for t, o, st in rows]
    return {"plan": {"steps": steps}, "marks": marks or {2: 100.0, 5: 200.0, 6: 300.0, 7: 310.0}, "scale": 10.0,
            "truth": truth, "verdict": {"verdict": verdict}}


def test_windows_settle_vent_and_pressure():
    ep = _toy([(101.0, {"f1_flow": 500}, {"f1_valve_pos": 50}),  # within step 2's settle (6 s wall): not counted
               (250.0, {"pressure": 2000, "purge_flow": 900}, {"purge_valve_pos": 100}),  # venting, before vent_close
               (400.0, {}, {})])
    assert score.conditions(ep, 0.001, FS) == {}
    ep = _toy([(107.0, {"f1_flow": 5}, {}), (305.0, {"pressure": 151}, {}), (307.0, {}, {"purge_valve_pos": 2})])
    hits = score.conditions(ep, 0.01, FS)
    assert set(hits) == {"pressure", "state:purge"}  # 5 = 0.5 % of f1: below the primary limit
    assert set(score.conditions(ep, 0.001, FS)) == {"pressure", "state:purge", "flow:f1"}
    assert set(score.conditions(ep, 0.001, FS, since=306.0)) == {"state:purge"}


def test_pressure_not_evaluated_if_vent_close_never_reached_and_skips():
    ep = _toy([(150.0, {"pressure": 2700}, {})], verdict="BLOCKED", marks={2: 100.0})
    assert score.conditions(ep, 0.01, FS) == {}  # steps after a block are not reached, not skipped
    ep = _toy([(400.0, {}, {})], marks={2: 100.0, 6: 300.0, 7: 310.0})
    assert set(score.conditions(ep, 0.01, FS)) == {"skipped:5"}


def test_score_output_passes_never_say_and_writes(batch, monkeypatch, tmp_path):
    s, _ = batch
    paths = score.write(dict(s), tmp_path)
    assert [p.name for p in paths] == ["score_p1.json", "score_p1.md"]
    assert "fault, below hazard limits" in paths[1].read_text(encoding="utf-8")
    monkeypatch.setattr(score, "never_say", lambda text: ["safe"])
    with pytest.raises(SystemExit, match="never-say"):
        score.write(dict(s), tmp_path / "x")


def test_real_never_say_checker_runs_on_score_output(batch):
    pytest.importorskip("zerostate.wording")
    s, _ = batch
    assert score.never_say(json.dumps(s, default=str)) == []

def test_camera_coverage_counts_timeouts_next_to_accuracy():
    reads = [{"note": "no frame: TimeoutError: timed out", "readable": False},
             {"note": "no frame: URLError: <urlopen error timed out>", "readable": False},
             {"note": "no frame: ConnectionRefusedError: refused", "readable": False},
             {"note": "read unavailable: HTTP 500", "readable": False},
             {"note": None, "readable": True, "located_by": "map"}]
    assert score.camera_coverage(reads, 2) == {"readings": 5, "readable": 1, "no_frame": 3, "timeouts": 2,
                                               "model_unavailable": 1, "located_by_map": 1, "pending_at_stop": 2}


BENCH2 = ROOT / "eval" / "results" / "bench" / "2"


@pytest.mark.skipif(not BENCH2.exists(), reason="batch 2 episodes not committed")
def test_with_camera_verdict_comes_from_verdict_json_when_the_camera_track_logged_none():
    """The with-camera track logs a verdict event only when its own verdict changes; verdict.json carries it always."""
    s0 = score.load_episode(next(BENCH2.glob("S0_seed1011091684_*")))
    s8 = score.load_episode(next(BENCH2.glob("S8_seed155989621_*")))
    assert not s0["track"]["with_camera"] and s8["track"]["with_camera"]
    r0, r8 = score.score_episode(s0, FS), score.score_episode(s8, FS)
    assert (r0["verdict_with_camera"], r0["camera_own_verdict"]) == (score.NO_DISC, False)
    assert (r8["verdict_with_camera"], r8["camera_own_verdict"]) == ("BLOCKED", True)


def test_plan_set_lists_manifest_entries_without_a_result(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"cases": [{"case": "PC0", "seed": 1, "blocked": False, "label_match": True},
                                       {"case": "PC1", "seed": 9, "blocked": True, "label_match": True}]}), encoding="utf-8")
    out = score.plan_set(p, {("plan", "PC0", 1), ("plan", "PC1", 2), ("p1", "S0", 3)})
    assert out["missing"] == ["PC1 seed 2"] and out["not_in_manifest"] == ["PC1 seed 9"]
    assert out["false_blocks"]["k"] == 0 and out["per_case"]["PC1"]["blocked"] == 1


def test_an_invalidated_attempt_is_listed_and_its_rerun_is_scored(tmp_path):
    """Batch p2's S2: the first episodes ran with no fault (run_benchmark --invalidate-unfired), the re-runs count."""
    res = tmp_path / "bench"
    res.mkdir()
    seed = int(CLEAN_PASS.split("_seed")[1].split("_")[0])
    old, new = f"S0_seed{seed}_20261104T090000", f"S0_seed{seed}_20261104T120000"
    _copy(CLEAN_PASS, res, old)
    _copy(CLEAN_PASS, res, new)
    att = {"kind": "attempt", "plant": "p1", "scenario": "S0", "seed": seed, "valid": True}
    (res / "progress.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
        {**att, "episode": old}, {**att, "kind": "invalidated", "episode": old, "reason": "drawn fault never fired"},
        {**att, "episode": new})), encoding="utf-8")
    m, s, h = _seal(tmp_path, [{"plant": "p1", "scenario": "S0", "seed": seed}])
    out = score.score("p1", m, s, res, hash_p=h, muse_results=tmp_path / "none.json")
    assert out["n_scored"] == 1 and out["invalid"] == {**out["invalid"], "k": 0, "attempts": 2, "invalid_attempts": 1}
    assert out["episode_problems"] == {old: ["invalidated: drawn fault never fired"]}
