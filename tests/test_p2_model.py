"""P2-6: the gas line model (plants/p2_gasline/model.py) behaves as SPEC.md says."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("p2_model", Path(__file__).parents[1] / "plants" / "p2_gasline" / "model.py")
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def isolated(seed=0):
    """Correct plan steps 1-4 done: F-210 shut in at D-220's pressure, cavity bled."""
    m = model.GasLine(seed=seed)
    for v, x in (("XV-201", 0), ("XV-203", 0), ("BV-202", 100), ("XV-204", 0)):
        m.command(v, x)
        m.step(60)
    return m


def test_normal_operation_is_steady_and_between_the_sources():
    m = model.GasLine(seed=0)
    before = {k: m.p(k) for k in model.VOLUMES}
    m.step(300)
    for k, p in before.items():
        assert m.p(k) == pytest.approx(p, abs=0.01)
    assert 1500 < m.p("F-210") < m.p("C-202") < 2000


def test_valve_travels_in_10_process_s_with_limit_switch_feedback():
    m = model.GasLine(seed=0)
    m.command("XV-201", 0)
    m.step(4.5)
    assert m.pos["XV-201"] == pytest.approx(55) and m.measure()["XV-201.FB"] == 50  # neither switch made
    m.step(6)
    assert m.pos["XV-201"] == 0 and m.measure()["XV-201.FB"] == 0
    assert m.measure()["XV-201.CMD"] == 0


def test_isolation_sequence_bleeds_the_cavity_and_holds_f210():
    m = isolated()
    assert m.p("C-202") == pytest.approx(model.PA, abs=0.5)
    p = m.p("F-210")
    m.step(600)
    assert m.p("F-210") == pytest.approx(p, abs=1e-6)


def test_leak_passes_flow_with_feedback_unchanged():
    m = isolated()
    m.set("XV-204.leak_pct", 1.0)
    m.command("VV-213", 100)
    while m.p("F-210") > 200:
        m.step(1.5)
    m.command("VV-213", 0)
    m.step(12)
    p = m.p("F-210")
    m.step(600)
    assert m.p("F-210") > p + 50 and m.measure()["XV-204.FB"] == 0


def test_blocked_vent_has_no_flow_and_no_fall():
    m = isolated()
    m.set("VV-213.flow_scale", 0)
    p = m.p("F-210")
    m.command("VV-213", 100)
    m.step(120)
    meas = m.measure()
    assert meas["VV-213.FB"] == 100 and meas["FT-213.PV"] <= 0.1 and m.p("F-210") == pytest.approx(p)


def test_feedback_faults_frozen_offset_fixed_and_stuck():
    m = model.GasLine(seed=0)
    m.set("XV-204.stuck", 1)
    m.set("XV-204.pos_fault_mode", 3)
    m.set("XV-204.pos_fault_severity", 0)
    m.command("XV-204", 0)
    m.step(30)
    assert m.pos["XV-204"] == 100 and m.measure()["XV-204.FB"] == 0
    m.set("XV-201.pos_fault_mode", 1)
    m.command("XV-201", 0)
    m.step(30)
    assert m.measure()["XV-201.FB"] == 100
    m.set("XV-203.pos_fault_mode", 2)
    m.set("XV-203.pos_fault_severity", -30)
    assert m.measure()["XV-203.FB"] == 70


def test_sensor_frozen_drift_dropout():
    m = isolated()
    m.set("PT-211.fault_mode", 1)
    held = m.measure()["PT-211.PV"]
    m.command("VV-213", 100)
    m.step(60)
    assert m.measure()["PT-211.PV"] == held and m.measure()["PT-212.PV"] < held - 300
    m.set("PT-212.fault_mode", 2)
    m.set("PT-212.fault_severity", -3600)  # kPa per process-hour
    m.step(100)
    assert m.measure()["PT-212.PV"] == pytest.approx(m.p("F-210") - 100, abs=3)
    m.set("PT-200.fault_mode", 4)
    m.set("PT-200.fault_severity", 0.5)
    seen = []
    for _ in range(20):
        m.step(1)
        seen.append(m.measure()["PT-200.PV"])
    assert seen.count(0.0) == 10


def test_noise_is_within_a_tenth_of_a_percent_of_span_and_seeded():
    a, b = model.GasLine(seed=7), model.GasLine(seed=7)
    va = [a.measure()["PT-211.PV"] for _ in range(500)]
    assert va == [b.measure()["PT-211.PV"] for _ in range(500)]
    assert max(abs(v - a.p("F-210")) for v in va) <= 2.5 and len(set(va)) > 400


def test_every_p2_scenario_fault_is_a_model_key():
    import yaml

    for f in sorted((Path(__file__).parents[1] / "eval" / "scenarios" / "p2").glob("*.yaml")):
        sc = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert sc["plant"] == "p2_gasline" and sc["id"] == f.stem and sc["expected"]
        m = model.GasLine(seed=0)
        for fault in sc.get("faults", []):
            for k, v in fault.get("set", {}).items():
                m.set(k, v[0] if isinstance(v, list) else v)


def test_psv_relieves_above_set_pressure():
    m = isolated()
    m.set("D-220.pressure_kpa", 2600)
    m.command("XV-204", 100)
    opened, peak = False, 0.0
    for _ in range(200):
        m.step(1.5)
        opened, peak = opened or m.pos["PSV-214"] == 100, max(peak, m.p("F-210"))
    assert opened and 2300 < peak < 2400

