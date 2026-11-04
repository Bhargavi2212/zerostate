"""P3-8 demo driver (P1 GRFICS, live): the plant side of a demo a person runs in the console.

The person marks each step in the ZeroState console (text or voice); a second person verifies isolate
steps there. When step k's mark shows in the audit log, this driver does what the runner's
eval-operator does after its own mark: k's valve actions on the simulator (same targets, states,
pauses, vent wait) and the scenario's fault at its seeded cue (S8: f1 feedback reads closed while f1
stays open). It marks, verifies, reopens, signs, stops and confirms nothing, and writes neither the
inbox nor the audit log: it reads `zs status --json` / `zs audit export` and moves the plant.

    python eval/tools/demo_driver.py --scenario S8 --seed 8 --camera
    python eval/tools/demo_driver.py --scenario S0 --seed 7
"""

import argparse
import importlib.util
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
RUNS = ROOT / "runs"
_spec = importlib.util.spec_from_file_location("runner", ROOT / "eval" / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

RUNNER_NAMES = ("eval-operator", "eval-verifier", "eval-runner")  # the benchmark's own marks are never a cue
REMIND_S = 600
POLL_S = 0.5
EXPORT_S = 5  # and at least this often, so a repeated mark that leaves the step map unchanged is still seen
SCENARIOS = ("S0", "S8")


def _done(st: dict) -> bool:
    return st["verdict"] in runner.TERMINAL or st["state"] in ("closed", "stopped")


def describe(step) -> str:
    if step.kind == "mode":
        return "PLC manual mode switched on by the operator"
    if step.kind in ("isolate", "vent_close"):
        return f"{', '.join(runner.step_targets(step))} closed by the operator"
    if step.kind == "vent_open":
        return f"{step.target} opened to {step.required_state:g} % by the operator"
    return f"{step.kind}: nothing moved"


class Demo(runner.Episode):
    """runner.Episode with the person's marks as cues: start(), schedule()/fire_due(), operate() and
    vent_down() are the runner's own; mark(), verify and session stop are never called."""

    def __init__(self, scenario: dict, seed: int, out: Path, camera: bool = False, remind_s: float = REMIND_S):
        super().__init__(scenario, seed, out, scoring=False, camera=camera)
        self.handled: set = set()  # audit event ids already read
        self.acted: set = set()  # steps the plant has been moved for
        self.remind_s = remind_s

    def events(self) -> list[dict]:
        return json.loads(runner.zs("audit", "export", self.sid))

    def wait_mark(self, k: int) -> tuple[dict, float | None]:
        """Poll until a person marks step k in order: (status, time seen). (status, None) when the
        session ends first. Other marks are reported and left to ZeroState; the plant is not touched."""
        last, read_t, since = None, 0.0, time.time()
        while True:
            self.fire_due()
            st = self.status()
            if _done(st):
                return st, None
            if st["steps"] != last or time.time() - read_t > EXPORT_S:  # the export is large: read it on change
                last, read_t = st["steps"], time.time()
                for e in self.events():
                    if e["id"] in self.handled or e["kind"] != "step_done":
                        continue
                    self.handled.add(e["id"])
                    p = e["payload"]
                    if p.get("by") in RUNNER_NAMES:
                        continue
                    self.log_event("mark_seen", p)
                    if int(p["k"]) == k and not p.get("out_of_order"):
                        return st, time.time()
                    why = "marked again" if int(p["k"]) in self.acted else "marked out of order"
                    print(f"step {p['k']} {why}: the plant is left as it is")
            if time.time() - since > self.remind_s:
                print(f"reminder: waiting for step {k} to be marked in the console (the driver never acts on its own)")
                since = time.time()
            time.sleep(POLL_S)

    def wait_end(self) -> dict:
        """After the last step: hold the plant as it is until the person signs or stops the session."""
        since = time.time()
        while True:
            self.fire_due()
            st = self.status()
            if _done(st):
                return st
            if time.time() - since > self.remind_s:
                print("reminder: the person signs or closes the session in the console")
                since = time.time()
            time.sleep(POLL_S)

    def drive(self) -> dict:
        self.pre, st = self.start()
        print(f"session {self.sid}\nready: mark step 1 in the console")
        for step in self.plan.steps:
            if _done(st) or step.kind == "final":
                break
            k = step.k
            self.schedule(k, None)  # faults tied to "before step k", at the point the runner fires them
            st, t_mark = self.wait_mark(k)
            if t_mark is None:
                break
            self.schedule(k, t_mark)
            if step.kind == "vent_open" and (problem := runner.vent_start_problem(self.last_pressure)):
                print(f"note: {problem}")
            self.operate(step)
            self.acted.add(k)
            self.log_event("operator_step", {"k": k, "kind": step.kind})
            print(f"step {k}: {describe(step)}; ZeroState is checking")
            st = self.evaluated(k)
            if step.kind == "isolate" and not _done(st):
                print(f"step {k}: a second person verifies it in the console")
            if step.kind == "vent_open" and not _done(st):
                print(f"venting to {self.plan.vent_target_kpa_abs:g} kPa; mark step {k + 1} when it is down")
                self.vent_down()
        if not _done(st):
            print(f"all steps marked, verdict {st['verdict'] or 'pending'}: the person signs or closes the session in the console")
            st = self.wait_end()
        if st["state"] in ("closed", "stopped"):
            print(f"session {st['state']} in the console, verdict {st['verdict']}")
        else:
            print(f"verdict {st['verdict']}: the session stays open; the person signs or closes it in the console")
        return st

    def restore(self) -> dict:
        """Plant back as the runner's postflight leaves it (faults cleared, operator AUTO). The session is
        left to the person."""
        self.stop_truth.set()
        if getattr(self, "pre", None):
            return runner.postflight(self.pre["ids_offset"], self.sc)
        runner.faults.clear()
        runner.operator("manual", "off")
        return {}


def parse(argv=None):
    ap = argparse.ArgumentParser(description="Live P1 demo: the person marks steps in the console; this driver moves "
                                             "the plant after each mark. Tuning seeds only (below 1000).")
    ap.add_argument("--scenario", required=True, choices=SCENARIOS)
    ap.add_argument("--seed", type=int, required=True, help="tuning seed, 0-999; scoring seeds are refused")
    ap.add_argument("--camera", action="store_true", help="use zs-frames, as the runner's --camera")
    ap.add_argument("--session", help="session id to start (default demo_<scenario>_seed<N>_<time>)")
    for refused in ("--batch", "--manifest", "--salt"):
        ap.add_argument(refused, help="refused: the demo never runs a sealed batch")
    a = ap.parse_args(argv)
    if a.batch or a.manifest or a.salt:
        ap.error("--batch, --manifest and --salt are refused: the demo runs tuning seeds only")
    if a.seed not in runner.TUNING_SEEDS:
        ap.error(f"seed {a.seed} refused: the demo runs tuning seeds only (0-{runner.TUNING_SEEDS.stop - 1})")
    return a


def main(argv=None) -> int:
    a = parse(argv)
    scenario = yaml.safe_load((ROOT / "eval" / "scenarios" / f"{a.scenario}.yaml").read_text(encoding="utf-8"))
    sid = a.session or f"demo_{a.scenario}_seed{a.seed}_{datetime.now(UTC):%Y%m%dT%H%M%S}"
    out = RUNS / sid
    out.mkdir(parents=True, exist_ok=False)
    demo = Demo(scenario, a.seed, out, camera=a.camera)
    images = {n: runner.sh("docker", "inspect", "--format", "{{.Image}}", n, check=False).strip()
              for n in ("simulation", "zerostate", "zs-operator", "plc", *(["zs-frames"] if a.camera else []))}
    meta = {"demo": True, "scenario": scenario, "seed": a.seed, "faults": demo.faults, "process_time_scale": demo.scale,
            "images": images, "plan_hash": demo.plan.content_hash(), "batch": None, "camera": a.camera}
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    rc, st = 1, None
    try:
        st = demo.drive()
        rc = 0
    except KeyboardInterrupt:
        print("stopped by Ctrl-C: the session is left to the person in the console")
    except runner.EpisodeInvalid as e:
        print(f"lab problem: {e}", file=sys.stderr)
    finally:
        try:
            post = demo.restore()
        except Exception as e:  # noqa: BLE001 - report it, the record still gets written
            post = {"problems": [f"restore failed: {e}"]}
        demo.log_event("end", {"status": st, "postflight": post})
        (out / "meta.json").write_text(json.dumps({**meta, "postflight": post}, indent=1), encoding="utf-8")
        print(f"plant restored (faults cleared, operator AUTO); record in {out}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
