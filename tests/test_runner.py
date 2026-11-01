"""eval/runner.py logic that runs without the lab: seeded draws and the router-rule order check."""

import importlib.util
import json
import random
from pathlib import Path

spec = importlib.util.spec_from_file_location("runner", Path(__file__).parents[1] / "eval" / "runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_draw_is_reproducible_by_seed_and_keeps_fixed_values():
    f = {"at_step": [5, 7], "after_process_s": [0.0, 30.0], "set": {"tank_pressure_fault_mode": 4, "sev": [0.3, 0.7]}}
    a, b = runner.draw(f, random.Random(7)), runner.draw(f, random.Random(7))
    assert a == b and a["at_step"] in (5, 6, 7) and 0 <= a["after_process_s"] <= 30
    assert a["set"]["tank_pressure_fault_mode"] == 4 and 0.3 <= a["set"]["sev"] <= 0.7


def chain(*lines):
    return "\n".join(["-P FORWARD DROP", *lines]) + "\n"


PAIRS = [f"-A FORWARD -s {s}/32 -d 192.168.95.2/32 -p tcp -m tcp --dport 502 -j ACCEPT\n-A FORWARD -s {s}/32 -j DROP"
         for s in runner.SOURCES]


def test_router_rules_must_sit_above_the_allow_all(monkeypatch):
    monkeypatch.setattr(runner, "sh", lambda *a, **k: chain(*PAIRS, "-A FORWARD -j ACCEPT"))
    assert runner.router_rules_ok()
    monkeypatch.setattr(runner, "sh", lambda *a, **k: chain("-A FORWARD -j ACCEPT", *PAIRS))
    assert not runner.router_rules_ok()
    monkeypatch.setattr(runner, "sh", lambda *a, **k: chain(PAIRS[0], "-A FORWARD -j ACCEPT"))
    assert not runner.router_rules_ok()


def test_step_evaluated_reads_json_string_keys():
    # zs status --json turns step numbers into string keys; the first live S0 stalled on this
    st = json.loads(json.dumps({"steps": {1: "PASS", 2: "pending"}}))
    assert runner.evaluated(st, 1)
    assert not runner.evaluated(st, 2) and not runner.evaluated(st, 3)


def test_operator_failure_makes_the_episode_invalid(monkeypatch):
    import pytest
    monkeypatch.setattr(runner, "operator", lambda *a: 1)
    with pytest.raises(runner.EpisodeInvalid):
        runner.act("set", "f1", "0")
    monkeypatch.setattr(runner, "operator", lambda *a: 2)  # timeout: only allowed while venting
    runner.act("wait-pressure-below", "102")
    with pytest.raises(runner.EpisodeInvalid):
        runner.act("set", "f1", "0")
