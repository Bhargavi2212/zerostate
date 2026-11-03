from checks.plan_synth import VALVE, plan, pmap
from zerostate.checks.plan import boxedin
from zerostate.models.verdict import FindingStatus as S

NODES = {"S": {"kind": "source"}, "V1": VALVE, "W": {"kind": "vessel"}, "H": {"kind": "heater"},
         "VV": {"kind": "vent", "device": "block_valve", "normal_state": "closed", "discharges_to": "atmosphere"}}
PIPES = "S-V1 V1-W W-H W-VV"
PSV = {"kind": "relief", "device": "relief_valve", "normal_state": "closed", "discharges_to": "flare"}
P = plan(points=[("V1", "proved")])


def test_pass_closed_relief_counts_as_a_path():
    assert boxedin.check(P, pmap(NODES | {"PSV": PSV}, PIPES + " W-PSV"), {}).status == S.PASS


def test_pass_vent_open_during_the_hold():
    p = plan(points=[("V1", "proved")], steps=[{"k": 1, "kind": "vent_open", "target": "VV"}, {"k": 2, "kind": "hold"}])
    assert boxedin.check(p, pmap(NODES, PIPES), {}).status == S.PASS


def test_fail_heater_boxed_in():
    f = boxedin.check(P, pmap(NODES, PIPES), {})
    assert f.status == S.FAIL and f.refs == ["H"] and f.path == ["H", "W"]
