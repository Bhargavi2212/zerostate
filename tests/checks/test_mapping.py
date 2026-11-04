from checks.plan_synth import VALVE, plan, pmap
from zerostate.checks.plan import mapping
from zerostate.models.verdict import FindingStatus as S

# S -> V1 -> W; PT-1 on the work vessel, PT-0 on the supply
M = pmap({"S": {"kind": "source"}, "V1": VALVE, "W": {"kind": "vessel"}}, "S-V1 V1-W",
         [{"tag": "PT-0", "signal_ref": "PT-0", "role": "pressure", "at": "S"},
          {"tag": "PT-1", "signal_ref": "PT-1", "role": "pressure", "at": "W"}])


def wit(ref, side):
    return {"segment": "W", "signal_ref": ref, "role": "pressure", "side": side}


def test_pass_tags_and_sides_match():
    p = plan(points=[("V1", "proved")], witnesses=[wit("PT-1", "work"), wit("PT-0", "upstream")])
    assert mapping.check(p, M, {}).status == S.PASS


def test_fail_gauge_on_the_wrong_side():
    f = mapping.check(plan(points=[("V1", "proved")], witnesses=[wit("PT-0", "work")]), M, {})
    assert f.status == S.FAIL and "PT-0 is on the upstream side" in f.message


def test_fail_tag_or_work_not_in_map():
    f = mapping.check(plan(work="X", points=[("V9", "proved")]), M, {})
    assert f.status == S.FAIL and "V9 is not in the plant map" in f.message and "work equipment X" in f.message
