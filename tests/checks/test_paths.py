from checks.plan_synth import LINE, VALVE, plan, pmap
from zerostate.checks.plan import paths
from zerostate.models.verdict import FindingStatus as S

# S -> V1 -> W <- V2 <- D (a second source: backflow)
TWO = pmap({"S": {"kind": "source"}, "V1": VALVE, "W": {"kind": "vessel"}, "V2": VALVE, "D": {"kind": "source"}},
           "S-V1 V1-W W-V2 V2-D")


def test_pass_every_source_blocked():
    assert paths.check(plan(points=[("V1", "proved"), ("V2", "proved")]), TWO, {}).status == S.PASS


def test_fail_missed_line_names_the_path():
    f = paths.check(plan(points=[("V1", "proved")]), TWO, {})
    assert f.status == S.FAIL and f.path == ["D", "V2", "W"] and "D -> V2 -> W" in f.message


def test_unknown_when_work_not_in_map():
    assert paths.check(plan(work="X"), LINE, {}).status == S.UNKNOWN
