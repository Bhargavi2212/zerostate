"""eval/claims_audit.py on a tmp claims.yaml + fake results; and the real eval/claims.yaml is well formed."""

import importlib.util
import json
import re
from pathlib import Path

import yaml

from zerostate.wording import hits

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("claims_audit", ROOT / "eval" / "claims_audit.py")
ca = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ca)

CLAIM = {"id": "C6.p1", "batch": "p1", "engine": "live checks only (Phase 1 engine)",
         "sentence": "On {false_blocks.n} clean episodes it falsely blocked {false_blocks.k} ({rate:.0%}).",
         "tests": ["tests/test_x.py"], "results": "eval/results/score_p1.json",
         "keys": ["false_blocks.n", "false_blocks.k", "rate"]}
RENDERED = "On 15 clean episodes it falsely blocked 1 (7%)."


def ok(tests, root):
    return 0


def setup(tmp_path, claim=CLAIM, readme=None, score=None):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (tmp_path / "eval" / "results").mkdir(parents=True)
    score = score or {"false_blocks": {"n": 15, "k": 1}, "rate": 1 / 15}
    (tmp_path / "eval" / "results" / "score_p1.json").write_text(json.dumps(score), encoding="utf-8")
    (tmp_path / "eval" / "claims.yaml").write_text(yaml.safe_dump({"claims": [claim]}), encoding="utf-8")
    if readme is not None:
        (tmp_path / "README.md").write_text(readme, encoding="utf-8")


def audit(tmp_path, claim=CLAIM, readme="", run=ok, commit=lambda t, r: "abc"):
    return ca.audit_claim(claim, tmp_path, readme, run, commit)


def test_passing_claim_renders(tmp_path):
    setup(tmp_path)
    r = audit(tmp_path)
    assert r["passing"] and r["rendered"] == RENDERED and not r["used"]


def test_missing_test_fails(tmp_path):
    setup(tmp_path)
    r = audit(tmp_path, {**CLAIM, "tests": ["tests/test_gone.py::test_a"]})
    assert not r["passing"] and r["why"] == ["missing test tests/test_gone.py::test_a"]


def test_failing_test_fails(tmp_path):
    setup(tmp_path)
    r = audit(tmp_path, run=lambda tests, root: 1)
    assert not r["passing"] and "tests not passing" in r["why"][0]


def test_missing_key_and_file_fail(tmp_path):
    setup(tmp_path, score={"false_blocks": {"n": 15}, "rate": 0.0})
    assert audit(tmp_path)["why"] == ["missing key false_blocks.k"]
    r = audit(tmp_path, {**CLAIM, "results": "eval/results/score_2.json"})
    assert "missing result file eval/results/score_2.json" in r["why"] and r["rendered"] is None


def test_placeholder_must_be_listed_in_keys(tmp_path):
    setup(tmp_path)
    r = audit(tmp_path, {**CLAIM, "keys": ["false_blocks.n", "false_blocks.k"]})
    assert "placeholder rate not in keys" in r["why"]


def test_require_and_tags(tmp_path):
    setup(tmp_path)
    r = audit(tmp_path, {**CLAIM, "require": {"false_blocks.k": 0}, "tags_same_commit": ["a", "b"]},
              commit=lambda t, root: {"a": "1", "b": "2"}[t])
    assert r["why"] == ["false_blocks.k is 1, claim needs 0", "tags on different commits: a, b"]
    r = audit(tmp_path, {**CLAIM, "tags_same_commit": ["a"]}, commit=lambda t, root: None)
    assert r["why"] == ["missing tag a"]


def test_newest_result_file_is_used(tmp_path):
    setup(tmp_path)
    res = tmp_path / "eval" / "results"
    (res / "read_2026-11-02.json").write_text(json.dumps({"n": 1}), encoding="utf-8")
    (res / "read_2026-11-03.json").write_text(json.dumps({"n": 2}), encoding="utf-8")
    claim = {**CLAIM, "sentence": "{n} frames", "keys": ["n"], "results": "eval/results/read_2*.json"}
    assert audit(tmp_path, claim)["rendered"] == "2 frames"


def test_readme_must_match_rendered_sentence(tmp_path, capsys):
    setup(tmp_path, readme=f"## Results\n{RENDERED[:20]}\n{RENDERED[20:]}\n")  # line-wrapped is fine
    assert ca.main(["--root", str(tmp_path)], run=ok) == 0
    assert "in README" in capsys.readouterr().out
    (tmp_path / "README.md").write_text("On 15 clean episodes it falsely blocked 0 (0%).", encoding="utf-8")
    assert ca.main(["--root", str(tmp_path)], run=ok) == 1
    assert "README sentence differs from the rendered one" in capsys.readouterr().out


def test_not_passing_claim_outside_readme_does_not_fail_the_run(tmp_path, capsys):
    setup(tmp_path)
    assert ca.main(["--root", str(tmp_path)], run=lambda tests, root: 1) == 0
    assert "NOT PASSING" in capsys.readouterr().out
    (tmp_path / "README.md").write_text(RENDERED, encoding="utf-8")
    assert ca.main(["--root", str(tmp_path)], run=lambda tests, root: 1) == 1


def test_never_say_word_in_output_fails(tmp_path, capsys):
    setup(tmp_path, claim={**CLAIM, "sentence": "The plant is safe.", "keys": []})
    assert ca.main(["--root", str(tmp_path)], run=ok) == 1
    assert "never-say" in capsys.readouterr().out


def test_real_pytest_run_counts_xfail_as_failing(tmp_path):
    (tmp_path / "test_a.py").write_text(
        "import pytest\n\ndef test_ok():\n    pass\n\n"
        "@pytest.mark.xfail(strict=True, reason='x')\ndef test_x():\n    assert False\n", encoding="utf-8")
    assert ca.pytest_rc(("test_a.py::test_ok",), tmp_path) == 0
    assert ca.pytest_rc(("test_a.py",), tmp_path) == 1


def test_real_claims_yaml_is_well_formed():
    claims = yaml.safe_load((ROOT / "eval" / "claims.yaml").read_text(encoding="utf-8"))["claims"]
    assert {c["id"].split(".")[0] for c in claims} == {f"C{i}" for i in range(1, 15)}
    assert len({c["id"] for c in claims}) == len(claims)
    for c in claims:
        assert str(c["batch"]) in {"p1", "2", "p2", "plan", "tests"}, c["id"]
        assert c["engine"] and not hits(c["sentence"] + c["engine"]), c["id"]
        assert [t for t in c.get("tests", []) if not (ROOT / t.split("::")[0]).exists()] == [], c["id"]
        assert {k for k, _ in ca.PLACEHOLDER.findall(c["sentence"])} <= set(c.get("keys", [])), c["id"]
        assert bool(c.get("keys")) == bool(c.get("results")), c["id"]
        if c["batch"] in ("p1", "2", "p2"):  # every batch figure names its batch in the sentence
            assert re.search(rf"\bbatch {c['batch']}\b", c["sentence"]), c["id"]


def test_src_diff_must_list_exactly_the_changed_files(tmp_path):
    """C2 after batch p2 re-froze: src/ between the two plants' tags differs only in the files the claim names."""
    setup(tmp_path)
    changes = {("a", "b"): ["src/x.py"], ("b", "c"): []}
    claim = {**CLAIM, "src_diff": [{"from": "a", "to": "b", "files": ["src/x.py"]}, {"from": "b", "to": "c"}]}
    assert ca.audit_claim(claim, tmp_path, "", ok, lambda t, r: "abc", lambda a, b, r: changes[(a, b)])["passing"]
    changes[("b", "c")] = ["src/y.py"]  # an unlisted change between the batch tags
    r = ca.audit_claim(claim, tmp_path, "", ok, lambda t, r: "abc", lambda a, b, r: changes[(a, b)])
    assert r["why"] == ["src/ changes b..c are ['src/y.py'], claim lists none"]
    r = ca.audit_claim(claim, tmp_path, "", ok, lambda t, r: "abc", lambda a, b, r: None)
    assert r["why"][0] == "cannot diff src/ a..b"


def test_real_src_diffs_of_c2_hold():
    """The real tags: the claim's file lists match git."""
    import yaml
    c2 = next(c for c in yaml.safe_load((ROOT / "eval" / "claims.yaml").read_text(encoding="utf-8"))["claims"] if c["id"] == "C2")
    for d in c2["src_diff"]:
        assert ca.git_src_changes(d["from"], d["to"], ROOT) == sorted(d.get("files") or []), d
