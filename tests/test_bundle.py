"""Episode bundle (docs/BUNDLE.md): export -> load -> schema validates; nothing key-like gets out."""

import importlib.util
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
