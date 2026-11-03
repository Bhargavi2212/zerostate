"""C10: verdict policy. No SAFE, FAIL beats UNKNOWN, never improves on its own, stamped verdicts."""

import ast
import itertools
from pathlib import Path

from checks.synth import HOLD, PARAMS, PLAN, STEP, steady, window

from zerostate import gate
from zerostate.models.evidence import Finding
from zerostate.models.verdict import FindingStatus as S
from zerostate.models.verdict import Verdict

SRC = Path(__file__).parents[1] / "src" / "zerostate"
NEVER_SAY = ("safe", "verifies isolation", "verified isolation", "certif", "zero energy", "never miss", "sil-")


def f(status):
    return Finding(rule_id="LIVE-X", rule_version="1", status=status, message="m")


def test_no_safe_member():
    assert not [v for v in Verdict if "SAFE" in v.name or "SAFE" in v.value]


def test_fail_beats_unknown_beats_pass_and_empty_is_not_a_pass():
    assert gate.combine([f(S.PASS), f(S.UNKNOWN), f(S.FAIL)]) == S.FAIL
    assert gate.combine([f(S.PASS), f(S.UNKNOWN)]) == S.UNKNOWN
    assert gate.combine([f(S.PASS)]) == S.PASS
    assert gate.combine([]) == S.UNKNOWN


def test_verdict_never_improves():
    states = [None, *Verdict]
    for old, new in itertools.product(states, states):
        assert gate.RANK[gate.worsen(old, new)] >= gate.RANK[old]


def test_no_discrepancy_only_when_the_plan_completes():
    assert gate.next_verdict(None, [f(S.PASS)]) is None
    assert gate.next_verdict(None, [f(S.PASS)], completes_plan=True) == Verdict.NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF
    assert gate.next_verdict(Verdict.ESCALATED, [f(S.PASS)], completes_plan=True) == Verdict.ESCALATED
    assert gate.next_verdict(Verdict.NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF, [f(S.FAIL)]) == Verdict.BLOCKED


def test_completes_plan_needs_every_step_passed():
    passed = {s.k: True for s in PLAN.steps if s.kind != "final"}
    assert gate.completes_plan(PLAN, passed, HOLD)
    assert not gate.completes_plan(PLAN, {**passed, 3: False}, HOLD)
    assert not gate.completes_plan(PLAN, passed, HOLD - 1)


def test_verdict_is_stamped():
    findings = gate.evaluate(PLAN, STEP[2], window(lambda ps: steady(pressure=2700.0, f1_flow=640.0), 80), PARAMS,
                             STEP[2].checks)
    s = gate.stamp(Verdict.BLOCKED, PLAN, PARAMS["version"], findings)
    assert s["plan_hash"] == PLAN.content_hash() and s["thresholds_version"] == PARAMS["version"]
    assert s["assumptions"] == ["positive isolation upstream assumed"]
    assert set(s["rules"]) == {"LIVE-QUALITY", "LIVE-ALIVE", "LIVE-RELATION", "LIVE-VALVE", "LIVE-HOLD", "LIVE-UPSTREAM",
                               "PLAN-PATHS", "PLAN-LIVESIDE", "PLAN-BOXEDIN", "PLAN-SOFTWARE", "PLAN-TYPE",
                               "PLAN-PROVING", "PLAN-MAPPING", "PROC-SEQUENCE"}
    assert any("reading closed" in r for r in s["reasons"])
    assert "plan_check_override" not in s
    assert gate.stamp(Verdict.BLOCKED, PLAN, PARAMS["version"], findings, "accepted")["plan_check_override"] == "accepted"


def test_user_facing_text_has_no_never_say_words():
    hits = []
    for py in [*(SRC / "checks").rglob("*.py"), SRC / "gate.py", SRC / "session.py", SRC / "cli.py"]:
        if not py.exists():
            continue
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                hits += [f"{py.name}: {node.value!r}" for w in NEVER_SAY if w in node.value.lower()]
    assert hits == []
