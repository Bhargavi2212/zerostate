"""eval/tools/demo_driver.py offline: a fake lab plays the console (scripted marks) and the plant.
The driver acts only on in-order marks by a person, fires S8's fault where the runner does, and
issues no mark / verify / reopen / sign / stop / confirm and no inbox or audit write."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_spec = importlib.util.spec_from_file_location("demo_driver", Path(__file__).parents[1] / "eval" / "tools" / "demo_driver.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)
runner = demo.runner

FORBIDDEN = {"done", "verify", "reopen", "sign", "stop", "confirm", "inbox", "inbox.sqlite", "audit.sqlite"}


class Lab:
    """The console side: marks arrive one at a time, two polls after the previous step was evaluated;
    a marked step passes on the next poll; after the last scripted mark the person signs."""

    def __init__(self, marks, block_at=None):
        self.marks = list(marks)  # (k, by, out_of_order)
        self.block_at, self.events, self.steps = block_at, [], {}
        self.verdict, self.state, self.cool = None, "ready", 2
        self.zs_calls, self.sh_calls, self.ops, self.timeline = [], [], [], []

    def _poll(self):
        pending = [k for k, v in self.steps.items() if v == "pending"]
        if pending:
            for k in pending:
                self.steps[k] = "PASS"
                self.timeline.append(("pass", int(k)))
                if self.block_at == int(k):
                    self.verdict = "BLOCKED"
            self.cool = 2
        elif self.cool:
            self.cool -= 1
        elif self.marks:
            k, by, ooo = self.marks.pop(0)
            self.events.append({"id": len(self.events) + 1, "kind": "step_done",
                                "payload": {"k": k, "by": by, **({"out_of_order": True} if ooo else {})}})
            self.steps[str(k)] = "pending"
            self.timeline.append(("mark", k))
        elif self.verdict is None:
            self.verdict = "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"
        else:
            self.state = "closed"  # the person signs in the console

    def zs(self, *args, check=True):
        self.zs_calls.append(args)
        if args[0] == "status":
            self._poll()
            return json.dumps({"state": self.state, "verdict": self.verdict, "steps": dict(self.steps), "stamp": None})
        if args[:2] == ("audit", "export"):
            return json.dumps(self.events)
        return ""

    def sh(self, *cmd, check=True, timeout=120):
        self.sh_calls.append(cmd)
        return ""

    def operator(self, *args):
        self.ops.append(args)
        self.timeline.append(("op", *args))
        return 0


@pytest.fixture
def lab_for(monkeypatch, tmp_path):
    def make(marks, block_at=None):
        lab = Lab(marks, block_at)
        monkeypatch.setattr(runner, "zs", lab.zs)
        monkeypatch.setattr(runner, "sh", lab.sh)
        monkeypatch.setattr(runner, "operator", lab.operator)
        monkeypatch.setattr(runner, "preflight", lambda: {"ids_offset": (0, "1")})
        monkeypatch.setattr(runner, "postflight", lambda off, sc: lab.timeline.append(("postflight",)) or {"valid": True})
        monkeypatch.setattr(runner.subprocess, "run", lambda cmd, **k: lab.sh_calls.append(tuple(cmd)) or SimpleNamespace(returncode=0))
        monkeypatch.setattr(runner.time, "sleep", lambda s: None)
        scale = runner.yaml.safe_load((runner.P1 / "modbus_map.yaml").read_text(encoding="utf-8"))["process_time_scale"]
        monkeypatch.setattr(runner, "truth", SimpleNamespace(read=lambda: {"state": {"zs_patch_version": "p1-1", "zs_time_scale": scale}}))
        monkeypatch.setattr(runner, "faults", SimpleNamespace(
            set_inputs=lambda **kw: lab.timeline.append(("fault", kw)) or {"state": kw}, clear=lambda: lab.timeline.append(("clear",))))
        monkeypatch.setattr(demo.Demo, "warm_up", lambda self: None)
        monkeypatch.setattr(demo.Demo, "truth_logger", lambda self: setattr(self, "last_pressure", 2700.0))
        monkeypatch.setattr(demo, "RUNS", tmp_path)
        return lab
    return make


def person(*ks):
    return [(k, "bhargavi", False) for k in ks]


def plant_moves(lab):
    return [op for op in lab.ops if op[0] != "manual" or op[1] == "on"]


CLEAN = [("manual", "on"), ("set", "f1"), ("set", "purge"), ("set", "f2"), ("set", "product"),
         ("set", "purge"), ("wait-pressure-below", "102.0"), ("set", "purge")]


def assert_read_only(lab):
    """Every zs call is a read; the only other commands are the runner's simulator recreate, image
    inspect and the session start (starting is not confirming)."""
    for args in lab.zs_calls:
        assert args[0] == "status" and args[2] == "--json" or args[:2] == ("audit", "export"), args
    for cmd in lab.sh_calls:
        assert not FORBIDDEN & set(cmd), cmd
        if "zerostate" in cmd:  # docker inspect zerostate, or docker exec ... zerostate zs session start
            assert cmd[cmd.index("zerostate") + 1:][:3] in ((), ("zs", "session", "start")), cmd
    for op in lab.ops:
        assert not FORBIDDEN & set(op), op


def test_marks_by_a_person_move_the_plant_in_order(lab_for, capsys):
    lab = lab_for(person(1, 2, 3, 4, 5, 6, 7))
    assert demo.main(["--scenario", "S0", "--seed", "7", "--session", "demo_t"]) == 0
    assert [op[:2] for op in plant_moves(lab)] == CLEAN
    seq = [e[:3] if e[0] == "op" else e for e in lab.timeline if e[0] == "mark" or e[0] == "op"]
    assert seq == [("mark", 1), ("op", "manual", "on"), ("mark", 2), ("op", "set", "f1"), ("op", "set", "purge"),
                   ("mark", 3), ("op", "set", "f2"), ("mark", 4), ("op", "set", "product"), ("mark", 5),
                   ("op", "set", "purge"), ("op", "wait-pressure-below", "102.0"), ("mark", 6), ("op", "set", "purge"),
                   ("mark", 7)]  # each step's moves follow its own mark, never ahead of it
    assert lab.timeline[-1] == ("postflight",)
    out = capsys.readouterr().out
    assert "ready: mark step 1 in the console" in out and "step 2: f1, purge closed by the operator; ZeroState is checking" in out
    assert "session closed in the console" in out
    assert_read_only(lab)
    rec = demo.RUNS / "demo_t"
    assert json.loads((rec / "meta.json").read_text())["demo"] is True
    kinds = [json.loads(l)["kind"] for l in (rec / "events.jsonl").read_text().splitlines()]
    assert kinds.count("operator_step") == 7 and kinds[-1] == "end"


def test_only_marked_steps_are_acted_on(lab_for):
    lab = lab_for(person(1, 2))  # the person stops after step 2, then signs (closes) the session
    demo.main(["--scenario", "S0", "--seed", "7", "--session", "demo_t"])
    assert [op[:2] for op in plant_moves(lab)] == CLEAN[:3]
    assert_read_only(lab)


def test_out_of_order_mark_gets_no_plant_action(lab_for, capsys):
    lab = lab_for([(1, "bhargavi", False), (3, "bhargavi", True), (2, "bhargavi", False)])
    demo.main(["--scenario", "S0", "--seed", "7", "--session", "demo_t"])
    assert [op[:2] for op in plant_moves(lab)] == CLEAN[:3]  # nothing for step 3: f2 never moved
    assert "step 3 marked out of order: the plant is left as it is" in capsys.readouterr().out
    assert_read_only(lab)


def test_the_runners_own_marks_are_no_cue(lab_for):
    lab = lab_for([(1, "eval-operator", False)])
    demo.main(["--scenario", "S0", "--seed", "7", "--session", "demo_t"])
    assert plant_moves(lab) == []


def test_s8_fault_fires_where_the_runner_fires_it(lab_for):
    lab = lab_for(person(1, 2), block_at=2)
    demo.main(["--scenario", "S8", "--seed", "8", "--session", "demo_t"])
    scen = runner.yaml.safe_load((runner.ROOT / "eval" / "scenarios" / "S8.yaml").read_text(encoding="utf-8"))
    want = scen["faults"][0]
    assert want["at_step"] == 2 and want["before_mark"]
    t = lab.timeline
    fault = t.index(("fault", want["set"]))
    # before step 2: after step 1 was evaluated, before the person's step 2 mark, before f1 is touched
    assert t.index(("pass", 1)) < fault < t.index(("mark", 2)) < t.index(("op", "set", "f1", "0.0"))
    assert [e for e in t if e[0] == "fault"] == [("fault", want["set"])]
    assert ("clear",) not in t or t.index(("clear",)) > fault
    assert ("postflight",) in t  # BLOCKED at step 2: the driver stops and restores the plant
    assert ("set", "f2") not in [op[:2] for op in lab.ops]
    assert_read_only(lab)


@pytest.mark.parametrize("argv", [["--seed", "1000"], ["--seed", "12345"], ["--seed", "7", "--batch", "p1"],
                                  ["--seed", "7", "--manifest", "m.yaml"], ["--seed", "7", "--salt", "s.txt"]])
def test_scoring_seed_or_sealed_batch_is_refused(argv, lab_for):
    lab = lab_for([])
    with pytest.raises(SystemExit) as e:
        demo.main(["--scenario", "S0", *argv])
    assert e.value.code == 2 and lab.sh_calls == [] and lab.zs_calls == []


def test_help_says_tuning_seeds_only(capsys):
    with pytest.raises(SystemExit):
        demo.parse(["--help"])
    assert "Tuning seeds only (below 1000)" in capsys.readouterr().out


def test_driver_source_has_no_write_command():
    src = (Path(demo.__file__)).read_text(encoding="utf-8")
    for bad in ('"step"', '"sign"', '"confirm"', '"verify"', '"reopen"', '"stop"', '"--by"', "inbox.sqlite", "audit.sqlite"):
        assert bad not in src, bad
