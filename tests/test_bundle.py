"""Episode bundle (docs/BUNDLE.md): export -> load -> schema validates; nothing key-like gets out."""

import gzip
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("export_bundle", ROOT / "eval" / "tools" / "export_bundle.py")
eb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eb)
RUN = min((ROOT / "eval" / "results" / "episodes").glob("S4-small_seed21_*"))  # blocked by LIVE-HOLD


def test_export_load_validates(tmp_path):
    b = eb.load(eb.write(eb.build(RUN), tmp_path))
    assert b.bundle_version == eb.BUNDLE_VERSION and b.episode == RUN.name
    assert b.result["verdict"] == "BLOCKED" and b.scenario == "S4-small"
    assert [s.k for s in b.steps] == [s["k"] for s in b.plan["steps"]] and b.steps[0].result == "PASS"
    assert any(f["rule_id"] == "LIVE-HOLD" and f["status"] == "FAIL" for e in b.evaluations for f in e.findings)
    assert b.truth["eval_only"] is True and len(b.truth["t"]) == len(b.truth["pressure"])
    assert all(t2 - t1 >= 1.0 for t1, t2 in zip(b.signals["t"], b.signals["t"][1:], strict=False))  # <= 1 Hz
    assert b.audit["chain_head"]


def test_key_like_strings_never_leave(tmp_path):
    b = eb.build(RUN)
    b.faults.append({"note": "Bearer sk-abcdefghijklmnopqrstuvwx"})
    with pytest.raises(SystemExit, match="key-like"):
        eb.write(b, tmp_path)
    assert not (tmp_path / "bundle.json.gz").exists()


def test_v2_fields_and_finding_ids(tmp_path):
    b = eb.load(eb.write(eb.build(RUN, runs_dir=tmp_path), tmp_path))
    assert b.bundle_version == "2" and b.signals_sha256 is None  # no full signals here, none recorded
    logged = json.loads((RUN / "audit_export.json").read_text(encoding="utf-8"))
    assert [f["id"] for e in b.evaluations for f in e.findings] == \
           [f"{e['id']}:{f['rule_id']}" for e in logged if e["kind"] == "evaluation" for f in e["payload"]["findings"]]
    marked = {e["payload"]["k"]: e["payload"]["by"] for e in logged if e["kind"] == "step_done"}
    assert {s.k: s.marked_by for s in b.steps if s.marked_by} == marked and all(s.reopened == [] for s in b.steps)
    start = next(e for e in logged if e["kind"] == "session_start")["payload"]
    assert b.confirmation == start.get("confirmation") and b.plan_check_override == start.get("plan_check_override")
    assert b.assumptions == [a["text"] for a in start["plan"].get("assumptions", [])]


def test_signals_hash_from_runs_dir_or_batch_file_and_mismatch_refused(tmp_path):
    run = tmp_path / "bench" / "p1" / RUN.name
    shutil.copytree(RUN, run)
    full = tmp_path / "runs" / RUN.name / "signals.jsonl"
    full.parent.mkdir(parents=True)
    full.write_text(json.dumps({"t": 1.0, "pressure": [2700.0, 1, "GOOD"]}) + "\n")
    digest = hashlib.sha256(full.read_bytes()).hexdigest()
    b = eb.build(run, runs_dir=tmp_path / "runs")
    assert b.signals_sha256 == digest and b.signals["t"] == [1.0] and b.signals["pressure"] == [2700.0]
    (run.parent / "signals_sha256.json").write_text(json.dumps({RUN.name: "f" * 64}))
    assert eb.build(run, runs_dir=tmp_path / "nothing").signals_sha256 == "f" * 64  # recorded, file not here
    with pytest.raises(SystemExit, match="does not match"):
        eb.build(run, runs_dir=tmp_path / "runs")


def test_v1_bundles_still_load(tmp_path):
    d = json.loads(eb.build(RUN).model_dump_json())
    for k in ("confirmation", "assumptions", "plan_check_override", "signals_sha256"):
        d.pop(k)
    for s in d["steps"]:
        for k in ("marked_by", "verified_by", "verified_t", "reopened"):
            s.pop(k)
    for e in d["evaluations"]:
        e.pop("point")
        for f in e["findings"]:
            f.pop("id")
    d["bundle_version"] = "1"
    p = tmp_path / "bundle.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(d, fh)
    b = eb.load(p)
    assert b.bundle_version == "1" and b.signals_sha256 is None and b.steps[0].marked_by is None
    from zerostate.api.replay import load_bundles
    from zerostate.api.server import detail

    rec = load_bundles(tmp_path)[RUN.name]  # replay mode reads v1 too
    s = detail(RUN.name, rec["events"])
    assert s["verdict"] == "BLOCKED" and s["steps"][0]["marked_by"] is None and s["steps"][0]["marked_t"] is not None
