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
    kinds = ["vent_open", "vent_close", "hold"]
    assert runner.draw({"at_step": kinds}, random.Random(3))["at_step"] in kinds


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


def test_vent_start_below_guard_is_invalid():
    assert runner.vent_start_problem(1499.9)
    assert runner.vent_start_problem(None)  # no truth sample yet: can't show the start was high enough
    assert runner.vent_start_problem(1500) is None


def test_scoring_seeds_need_the_benchmark_plan():
    other = "0" * 64
    assert runner.seed_problem(7, other) is None  # tuning seeds may run any plan (smoke)
    assert runner.seed_problem(1000, other)
    p1 = runner.BENCHMARK_PLAN_HASH["p1"]
    assert runner.seed_problem(1000, p1) is None
    assert runner.seed_problem(1000, p1, "p1") is None
    assert runner.seed_problem(-1, p1)
    assert "p1 benchmark plan" in runner.seed_problem(1000, other, "p1")


def test_plan_hash_is_per_plant_and_unconfirmed_refuses(monkeypatch):
    assert set(runner.BENCHMARK_PLAN_HASH) == {"p1", "p2"}
    monkeypatch.setitem(runner.BENCHMARK_PLAN_HASH, "p2", None)
    p1 = runner.BENCHMARK_PLAN_HASH["p1"]
    assert "no benchmark plan confirmed for p2" in runner.seed_problem(1000, p1, "p2")
    assert runner.seed_problem(7, p1, "p2") is None  # tuning seeds (smoke) still run
    monkeypatch.setitem(runner.BENCHMARK_PLAN_HASH, "p2", "a" * 64)
    assert runner.seed_problem(1000, "a" * 64, "p2") is None
    assert runner.seed_problem(1000, p1, "p2")  # P1's plan is not P2's


def test_benchmark_plan_is_the_committed_plan():
    plan = runner.IsolationPlan.model_validate(runner.yaml.safe_load(
        (runner.P1 / "envelope.yaml").read_text(encoding="utf-8")))
    assert plan.content_hash() == runner.BENCHMARK_PLAN_HASH["p1"]
    assert plan.camera == "optional"  # batch 2 runs the camera on P1
    # the active benchmark hashes are exactly what the owner confirmed (plants/<p>/confirmed.yaml)
    for p in ("p1_grfics", "p2_gasline"):
        book = runner.yaml.safe_load((runner.ROOT / "plants" / p / "confirmed.yaml").read_text(encoding="utf-8"))
        assert runner.BENCHMARK_PLAN_HASH[p[:2]] in {r["plan_hash"] for r in book}
    assert any(s.targets for s in plan.steps)  # block-in


def test_meta_gets_the_signals_hash(tmp_path):
    import hashlib
    (tmp_path / "meta.json").write_text(json.dumps({"seed": 7}))
    assert runner.add_signals_hash(tmp_path) is None  # copy failed: recorded as missing, not invented
    assert json.loads((tmp_path / "meta.json").read_text()) == {"seed": 7, "signals_sha256": None}
    (tmp_path / "signals.jsonl").write_bytes(b'{"t": 1}\n{"t": 2}\n')
    h = runner.add_signals_hash(tmp_path)
    assert h == hashlib.sha256(b'{"t": 1}\n{"t": 2}\n').hexdigest()
    assert json.loads((tmp_path / "meta.json").read_text()) == {"seed": 7, "signals_sha256": h}



# ---------------------------------------------------------------- P2 (offline, stubbed lab)
P2_PAIRS = [f"-A FORWARD -s {s}/32 -d 192.168.95.2/32 -p tcp -m tcp --dport 502 -j ACCEPT\n"
            f"-A FORWARD -s {s}/32 -d 192.168.95.50/32 -p tcp -m tcp --dport 4840 -j ACCEPT\n"
            f"-A FORWARD -s {s}/32 -j DROP" for s in runner.SOURCES]


def test_p2_router_rules_need_4840_above_the_drop(monkeypatch):
    monkeypatch.setattr(runner, "sh", lambda *a, **k: chain(*P2_PAIRS, "-A FORWARD -j ACCEPT"))
    assert runner.router_rules_ok(runner.P2_TARGETS) and runner.router_rules_ok()
    monkeypatch.setattr(runner, "sh", lambda *a, **k: chain(*PAIRS, "-A FORWARD -j ACCEPT"))
    assert runner.router_rules_ok() and not runner.router_rules_ok(runner.P2_TARGETS)  # P1 rules only


def test_p2_write_log_counts_users():
    log = "\n".join(json.dumps(r) for r in [{"user": "operator", "allowed": True}, {"user": "zerostate", "allowed": False},
                                            {"user": "operator", "allowed": False}])
    assert runner.p2_writes(log) == {"zerostate": 1, "operator_allowed": 1, "other": 0}
    assert runner.p2_writes("") == {"zerostate": 0, "operator_allowed": 0, "other": 0}


def test_p2_plan_file_is_the_merge_the_owner_confirms():
    """plants/p2_gasline/plan.yaml (confirmed by the owner, like P1's envelope) must hash like a fresh merge."""
    f = runner.IsolationPlan.model_validate(runner.yaml.safe_load((runner.P2 / "plan.yaml").read_text(encoding="utf-8")))
    assert f.content_hash() == runner.p2_plan().content_hash()


def test_p2_plan_and_code_spec():
    plan = runner.p2_plan()
    assert [(s.k, s.kind, s.target) for s in plan.steps][:5] == [
        (1, "isolate", "XV-201"), (2, "isolate", "XV-203"), (3, "vent_open", "BV-202"), (4, "isolate", "XV-204"), (5, "vent_open", "VV-213")]
    vent = next(s for s in plan.steps if s.k == 5)
    final_vent = next(s for s in plan.steps if s.k == 8)
    bleed = next(s for s in plan.steps if s.k == 3)
    assert runner.p2_vent_wait(plan, vent, 5) == ("PT-211", plan.hold_pressure_kpa_abs)
    assert runner.p2_vent_wait(plan, final_vent, 5) == ("PT-211", plan.vent_target_kpa_abs)
    assert runner.p2_vent_wait(plan, bleed, 5) == ("PT-202", plan.vent_target_kpa_abs)
    for _, _, local, pat in runner.CODE_SPEC_P2:
        assert list((runner.ROOT / local).glob(pat)), (local, pat)
    assert runner.BENCHMARK_PLAN_HASH["p2"] == plan.content_hash()


class FakeLab:
    """zs status / step / session for a clean P2 run: each marked step passes; the 8th gives the end verdict."""

    def __init__(self):
        self.steps, self.ops, self.verified, self.sh = {}, [], [], []

    def zs(self, *args, check=True):
        if args[0] == "status":
            done = "8" in self.steps
            return json.dumps({"state": "ready", "verdict": "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF" if done else "PENDING",
                               "steps": self.steps, "stamp": "x"})
        if args[:2] == ("step", "done"):
            self.steps[args[3]] = "PASS"
        if args[:2] == ("step", "verify"):
            self.verified.append((args[3], args[5]))
        return "{}"

    def run_sh(self, *cmd, check=True, timeout=120):
        self.sh.append(cmd)
        return json.dumps({"user": "operator", "allowed": True}) + "\n" if "cat" in cmd[-1] else ""


def p2_episode(tmp_path, monkeypatch, scenario):
    from types import SimpleNamespace
    lab = FakeLab()
    monkeypatch.setattr(runner, "zs", lab.zs)
    monkeypatch.setattr(runner, "sh", lab.run_sh)
    monkeypatch.setattr(runner, "router_rules_ok", lambda *a: True)
    monkeypatch.setattr(runner, "operator_p2", lambda *a: lab.ops.append(a) or 0)
    monkeypatch.setattr(runner, "operator", lambda *a: (_ for _ in ()).throw(AssertionError("P1 operator used")))
    compose = []
    monkeypatch.setattr(runner.subprocess, "run", lambda cmd, **k: compose.append(cmd) or SimpleNamespace(returncode=0, stderr=""))
    ep = runner.P2Episode(scenario, 7, tmp_path)
    fired = []
    ep.p2faults = SimpleNamespace(read=lambda: {"updating": True, "time_scale": ep.scale, "pressure_kpa_abs": {"F-210": 2000.0}},
                                  set_inputs=lambda **kw: fired.append(kw), updates=lambda on: fired.append(("updates", on)),
                                  clear=lambda: fired.append("clear"))

    class Stream:
        def __init__(self, hz):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

        def __iter__(self):
            yield {"t": 1.0, "pressure_kpa_abs": {"F-210": 2000.0}}
    monkeypatch.setattr(runner, "_load", lambda name, folder=None: SimpleNamespace(stream=Stream))
    return ep, lab, compose, fired


def test_p2_clean_episode_uses_the_p2_path(tmp_path, monkeypatch):
    scenario = runner.yaml.safe_load((runner.ROOT / "eval" / "scenarios" / "p2" / "S0.yaml").read_text(encoding="utf-8"))
    ep, lab, compose, fired = p2_episode(tmp_path, monkeypatch, scenario)
    r = ep.run()
    assert r["valid"] and r["match"], r
    assert "--profile" in compose[0] and compose[0][-1] == "p2"
    sets = [a[1:] for a in lab.ops if a[0] == "set"]
    assert sets == [("XV-201", "0.0"), ("XV-203", "0.0"), ("BV-202", "100.0"), ("XV-204", "0.0"),
                    ("VV-213", "100.0"), ("VV-213", "0.0"), ("VV-213", "100.0")]
    waits = [a[1:3] for a in lab.ops if a[0] == "wait-pressure-below"]
    assert waits == [("PT-202", "102.0"), ("PT-211", "200.0"), ("PT-211", "102.0")]
    assert lab.verified == [("1", "eval-verifier"), ("2", "eval-verifier"), ("4", "eval-verifier")]
    start = next(c for c in lab.sh if "session" in c)
    assert "ZS_MAP=/app/config/p2_gasline/opcua_map.yaml" in start and "/app/config/p2_gasline/plan.yaml" in start
    assert "clear" in fired


def test_p2_wrong_valve_and_same_verifier_variants(tmp_path, monkeypatch):
    ep, lab, _, _ = p2_episode(tmp_path, monkeypatch, {"id": "S5", "expected": ["BLOCKED"], "operator": "wrong_valve_step4"})
    ep.run()
    assert ("set", "XV-231", "0.0") in lab.ops and ("set", "XV-204", "0.0") not in lab.ops
    ep, lab, _, _ = p2_episode(tmp_path / "b", monkeypatch, {"id": "S7-same", "expected": ["BLOCKED"], "operator": "same_verifier"})
    (tmp_path / "b").mkdir()
    ep.run()
    assert lab.verified[0] == ("1", "eval-operator")


def test_p2_fault_actions(tmp_path, monkeypatch):
    ep, _, _, fired = p2_episode(tmp_path, monkeypatch, {"id": "S12", "expected": ["ESCALATED"]})
    ep.due = [(0.0, {"action": "stop_updates"}), (0.0, {"set": {"VV-213.flow_scale": 0}})]
    ep.fire_due()
    assert fired == [("updates", False), {"VV-213.flow_scale": 0}]
    ep.p2faults.set_inputs = lambda **kw: (_ for _ in ()).throw(RuntimeError("unknown key"))
    ep.due = [(0.0, {"set": {"nope": 1}})]
    import pytest
    with pytest.raises(runner.EpisodeInvalid):
        ep.fire_due()


def test_p2_env_takes_only_p2_passwords_from_the_env_file(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('MODEL_API_KEY=k\nP2_PASSWORD_OPERATOR="op"\nP2_PASSWORD_ZEROSTATE=zs\n')
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("P2_PASSWORD_OPERATOR", raising=False)
    monkeypatch.setenv("P2_PASSWORD_ZEROSTATE", "from-shell")
    env = runner.p2_env(f)
    assert env["P2_PASSWORD_OPERATOR"] == "op" and env["P2_PASSWORD_ZEROSTATE"] == "from-shell"
    assert "MODEL_API_KEY" not in env  # the model key never goes to a plant or the operator
