"""P1-1 live checks of the patched simulator, run from the host against the running lab.

Modbus is read inside the zerostate container (the host can't reach the macvlan network);
truth comes from the GRFICS web API on localhost.
"""

import importlib.util
import json
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
P1 = Path(__file__).parents[2] / "plants" / "p1_grfics"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, P1 / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


faults, truth = _load("faults"), _load("truth")
IR = {"f1_valve_pos": 100, "f1_flow": 101, "f2_valve_pos": 102, "f2_flow": 103, "purge_valve_pos": 104,
      "purge_flow": 105, "product_valve_pos": 106, "product_flow": 107, "pressure": 108, "level": 109,
      "a_in_purge": 110, "b_in_purge": 111, "c_in_purge": 112}


def scan(seconds: int) -> list[dict]:
    out = f"/tmp/live_{time.time_ns()}.json"
    subprocess.run(["docker", "exec", "zerostate", "python", "scripts/modbus_scan.py",
                    "--seconds", str(seconds), "--out", out], capture_output=True, check=False, timeout=seconds + 60)
    r = subprocess.run(["docker", "exec", "zerostate", "cat", out], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)["samples"]


@pytest.fixture(autouse=True)
def clean_faults():
    faults.clear()
    yield
    faults.clear()


def test_patch_version():
    assert truth.read()["state"]["zs_patch_version"] == "p1-1"


def test_noise_on_modbus():
    t = truth.read()
    samples = scan(30)
    spans = {"f1_flow": 1000, "f2_flow": 500, "purge_flow": 2000, "product_flow": 500}
    true_flow = {k: t["outputs"][k] for k in spans}
    for tag, addr in IR.items():
        raws = [s["ir"][str(addr)] for s in samples if s["ir"]]
        if tag in spans and true_flow[tag] < 0.01 * spans[tag]:
            assert set(raws) == {0}, f"{tag} below cutoff must read exactly 0"
        elif tag.endswith("_valve_pos") and t["state"][tag] in (0.0, 100.0):
            continue  # at an end stop the clamp halves the noise; not noise-carrying (constant_ok_raw)
        elif tag in spans and tag in ("purge_flow", "product_flow"):
            assert len(set(raws)) >= 10, tag  # controller duty cycle may hold them at 0 part of the time
        else:
            assert len(set(raws)) >= 20, f"{tag}: only {len(set(raws))} distinct raws in 30 s"


def test_feedback_tracks_truth_on_steady_valves():
    t = truth.read()
    s = scan(2)[-1]
    for v in ("f1", "f2"):
        fb = s["ir"][str(IR[f"{v}_valve_pos"])] / 65535 * 100
        assert abs(fb - t["state"][f"{v}_valve_pos"]) <= 0.3, v


def test_position_fault_reads_closed_while_open_and_persists():
    faults.set_inputs(f1_pos_fault_mode=3, f1_pos_fault_severity=0)
    time.sleep(5)  # several remote-I/O write cycles
    t = truth.read()
    assert t["state"]["f1_pos_fault_mode"] == 3, "fault did not persist across remote-I/O writes"
    assert t["state"]["f1_valve_pos"] > 50
    s = scan(2)[-1]
    assert s["ir"][str(IR["f1_valve_pos"])] / 65535 * 100 <= 0.3


def operator(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "exec", "zs-operator", "python", "operator.py", *args],
                          capture_output=True, text=True, timeout=300, check=False)


def test_leak_flows_through_a_valve_reading_closed():
    """Needs the operator (P1-3) to close f1 through manual mode; restores AUTO afterwards."""
    scale = str(truth.read()["state"]["zs_time_scale"])
    try:
        assert operator("manual", "on").returncode == 0
        assert operator("set", "f1", "0").returncode == 0
        assert operator("wait-valve", "f1", "0", "--timeout-process-s", "60", "--process-time-scale", scale).returncode == 0
        faults.set_inputs(f1_leak_pct=2)
        time.sleep(3)
        s = scan(3)[-1]
        flow = s["ir"][str(IR["f1_flow"])] / 65535 * 1000
        feedback = s["ir"][str(IR["f1_valve_pos"])] / 65535 * 100
        assert abs(flow - 12.8) <= 3, flow  # 6.4046 x 2 % opening
        assert feedback <= 0.3, feedback
    finally:
        faults.clear()
        operator("manual", "off")
