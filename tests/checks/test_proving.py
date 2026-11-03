from checks.plan_synth import VALVE, plan, pmap
from zerostate.checks.plan import proving
from zerostate.models.verdict import FindingStatus as S

# S -> V1 -> W, bleed BV on W; D a second source with its own header
M = pmap({"S": {"kind": "source"}, "V1": VALVE, "W": {"kind": "vessel"},
          "BV": {"kind": "bleed", "device": "block_valve", "normal_state": "closed", "discharges_to": "atmosphere"},
          "D": {"kind": "source"}}, "S-V1 V1-W W-BV")


def test_pass_bleed_to_atmosphere():
    assert proving.check(plan(points=[("V1", "proved")], proving=[("BV", ["V1"], "atmosphere")]), M, {}).status == S.PASS


def test_fail_no_proving_point():
    f = proving.check(plan(points=[("V1", "proved")]), M, {})
    assert f.status == S.FAIL and "no proving point" in f.message


def test_fail_bleed_into_a_pressurised_header():
    f = proving.check(plan(points=[("V1", "proved")], proving=[("BV", ["V1"], "header:D")]), M, {})
    assert f.status == S.FAIL and "discharges to D, which is pressurised" in f.message
