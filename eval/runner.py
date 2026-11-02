"""P1 episode runner (host). One episode = one scenario at one seed, end to end:

preflight (router + IDS rules, noise floor off, IDS log offset, operator in AUTO) -> recreate the
patched simulator -> warm up -> ZeroState session -> operator performs each plan step, marked only
after the previous step is evaluated -> scenario fault at its seeded onset -> stop at a terminal
verdict or after the hold -> postflight (rules still there, IDS: 0 ZeroState writes and > 0
operator writes). Episodes are pre-registered by seed and replayable from logs.

    python eval/runner.py --plant p1 --scenario S0 --seed 7
"""

import argparse
import importlib.util
import json
import os
import random
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from zerostate.models.envelope import IsolationPlan, step_targets

ROOT = Path(__file__).parents[1]
GRFICS = ROOT.parent
P1 = ROOT / "plants" / "p1_grfics"
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", str(ROOT / "deploy" / "docker-compose.zerostate.yml")]
SOURCES = ("192.168.90.60", "192.168.90.70")
PLC = "192.168.95.2"
TERMINAL = ("BLOCKED", "ESCALATED")
IO_DEVICES = "python (feed1|feed2|purge|product|tank|analyzer).py"  # GRFICS remote I/O device scripts
MIN_VENT_START_KPA = 1500  # below this the vent rules get too little range to judge: episode INVALID
TUNING_SEEDS = range(1000)  # anything else is a scoring seed
# hash of the committed block-in plan (P1), a plan digest, not a secret
BENCHMARK_PLAN_HASH = "89adfcf4fbb0a8e2b058c02ceed5d879d0a72312da92024bf967c8aec14f2a92"  # pragma: allowlist secret


def _load(name):
    spec = importlib.util.spec_from_file_location(name, P1 / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


faults, truth = _load("faults"), _load("truth")


class EpisodeInvalid(Exception):
    """Preflight/postflight failed: the episode can't count, whatever ZeroState said."""


def sh(*cmd, check=True, timeout=120) -> str:
    r = subprocess.run(list(cmd), check=False, capture_output=True, text=True, timeout=timeout, cwd=GRFICS)
    if check and r.returncode != 0:
        raise EpisodeInvalid(f"{' '.join(cmd)} -> {r.returncode}: {r.stderr.strip()[:300]}")
    return r.stdout


def zs(*args, check=True) -> str:
    return sh("docker", "exec", "-u", "zs", "zerostate", "zs", *args, check=check)


def act(*args) -> None:
    """An operator action the episode depends on: a failed write makes the episode invalid,
    never a ZeroState result (wait-pressure-below's timeout, exit 2, is allowed)."""
    rc = operator(*args)
    if rc not in (0, 2) or (rc == 2 and args[0] != "wait-pressure-below"):
        raise EpisodeInvalid(f"operator {' '.join(args)} failed (exit {rc})")


def operator(*args) -> int:
    return subprocess.run(["docker", "exec", "zs-operator", "python", "operator.py", *args],
                          check=False, capture_output=True, text=True, timeout=1800).returncode


def evaluated(status: dict, k: int) -> bool:
    """True once step k has a result. Status comes back as JSON, so step numbers are string keys."""
    return status["steps"].get(str(k)) not in (None, "pending")


def seed_problem(seed: int, plan_hash: str) -> str | None:
    """Scoring seeds run only on the committed block-in plan, so a benchmark never mixes plans."""
    if seed < 0:
        return "seed must be >= 0"
    if seed not in TUNING_SEEDS and plan_hash != BENCHMARK_PLAN_HASH:
        return f"scoring seed {seed} refused: plan hash {plan_hash[:12]} is not the benchmark plan {BENCHMARK_PLAN_HASH[:12]}"
    return None


def vent_start_problem(p_kpa: float | None) -> str | None:
    if p_kpa is None or p_kpa < MIN_VENT_START_KPA:
        return f"vent start {p_kpa} kPa below {MIN_VENT_START_KPA}: too little range for the vent rules"
    return None


def draw(spec, rng: random.Random):
    """Scenario values: [lo, hi] floats/ints are drawn from the seed; anything else is used as is."""
    if isinstance(spec, list) and len(spec) == 2 and all(isinstance(x, (int, float)) for x in spec):
        lo, hi = spec
        return rng.randint(lo, hi) if all(isinstance(x, int) for x in spec) else rng.uniform(lo, hi)
    if isinstance(spec, list) and spec and all(isinstance(x, str) for x in spec):
        return rng.choice(spec)  # e.g. a step kind drawn from [vent_open, vent_close, hold]
    if isinstance(spec, dict):
        return {k: draw(v, rng) for k, v in spec.items()}
    return spec


# ---------------------------------------------------------------- pre / postflight
def router_rules_ok() -> bool:
    chain = sh("docker", "exec", "router", "iptables", "-S", "FORWARD").splitlines()
    i_all = chain.index("-A FORWARD -j ACCEPT") if "-A FORWARD -j ACCEPT" in chain else len(chain)
    for src in SOURCES:
        allow = f"-A FORWARD -s {src}/32 -d {PLC}/32 -p tcp -m tcp --dport 502 -j ACCEPT"
        drop = f"-A FORWARD -s {src}/32 -j DROP"
        if allow not in chain or drop not in chain or not chain.index(allow) < chain.index(drop) < i_all:
            return False
    return True


def ids_position() -> tuple[int, str]:
    size, inode = sh("docker", "exec", "router", "stat", "-c", "%s %i", "/var/log/suricata/eve.json").split()
    return int(size), inode


def ids_counts(offset: tuple[int, str]) -> dict:
    size, inode = ids_position()
    rotated = size < offset[0] or inode != offset[1]
    start = 1 if rotated else offset[0] + 1  # a rotated log is counted from its start (conservative)
    out = {"rotated": rotated}
    for sid in ("9100001", "9100002"):
        n = sh("docker", "exec", "router", "sh", "-c",
               f"tail -c +{start} /var/log/suricata/eve.json | grep -c '\"signature_id\":{sid}' || true")
        out[sid] = int(n.strip() or 0)
    return out


PUBLISH = ("audit_export.json", "verdict.json", "meta.json", "ids.json", "events.jsonl")


def publish(run: Path) -> Path:
    """Copy what anyone needs to replay and score an episode into eval/results/episodes/ (committed);
    truth is gzipped. signals.jsonl stays in runs/ (it is the same data the audit windows carry)."""
    import gzip
    import shutil
    dest = ROOT / "eval" / "results" / "episodes" / run.name
    dest.mkdir(parents=True, exist_ok=True)
    for name in PUBLISH:
        if (run / name).exists():
            shutil.copyfile(run / name, dest / name)
    if (run / "truth.jsonl").exists():
        with open(run / "truth.jsonl", "rb") as src, gzip.open(dest / "truth.jsonl.gz", "wb") as dst:
            shutil.copyfileobj(src, dst)
    return dest


def preflight() -> dict:
    if not router_rules_ok():
        raise EpisodeInvalid("router rules for .60/.70 missing or below the allow-all: run apply_router_rules.ps1")
    if "RUNNING" not in sh("docker", "exec", "router", "supervisorctl", "status", "suricata", check=False):
        raise EpisodeInvalid("Suricata not running")
    sh("docker", "exec", "router", "test", "-f", "/etc/suricata/rules/zerostate.rules")
    nf = sh("docker", "exec", "simulation", "sh", "-c", "cat /app/noise_floor/state.json 2>/dev/null || echo '{}'")
    if json.loads(nf or "{}").get("enabled", False):
        raise EpisodeInvalid("noise-floor scheduler is enabled")
    if operator("manual", "off") != 0:
        raise EpisodeInvalid("operator could not restore AUTO")
    return {"ids_offset": ids_position()}


def postflight(offset, scenario) -> dict:
    if scenario.get("stopped_modbus"):
        sh("docker", "exec", "simulation", "supervisorctl", "start", "modbus", check=False)  # fresh device set
    faults.clear()
    operator("manual", "off")
    ids = ids_counts(offset)
    problems = []
    if not router_rules_ok():
        problems.append("router rules changed during the episode")
    if ids["9100001"] != 0:
        problems.append(f"ZeroState Modbus writes seen by the IDS: {ids['9100001']}")
    if ids["9100002"] == 0:
        problems.append("operator writes not seen by the IDS (rule or visibility broken)")
    return {"ids": ids, "valid": not problems, "problems": problems}


# ---------------------------------------------------------------- episode
class Episode:
    def __init__(self, scenario: dict, seed: int, out: Path):
        self.sc, self.seed, self.out = scenario, seed, out
        self.rng = random.Random(seed)
        self.faults = [draw(f, self.rng) for f in scenario.get("faults", [])]  # steps, onsets, severities
        self.plan_path = P1 / "envelope.yaml"
        self.plan = IsolationPlan.model_validate(yaml.safe_load(self.plan_path.read_text(encoding="utf-8")))
        self.scale = yaml.safe_load((P1 / "modbus_map.yaml").read_text(encoding="utf-8"))["process_time_scale"]
        self.sid = out.name
        self.due: list[tuple[float, dict]] = []
        self.stop_truth = threading.Event()
        self.last_truth_t = None  # Docker VM clock, same as ZeroState's audit timestamps
        self.last_pressure = None
        self.session_started = False

    # faults ------------------------------------------------------------
    def schedule(self, k: int, t_mark: float | None) -> None:
        kind = next(s.kind for s in self.plan.steps if s.k == k)
        for f in self.faults:
            if f.get("at_step") in (k, kind) and (f.get("before_mark") if t_mark is None else not f.get("before_mark")):
                delay = 0.0 if t_mark is None else draw(f.get("after_process_s", [0, 0]), self.rng) / self.scale
                self.due.append(((t_mark or time.time()) + delay, f))
        self.fire_due()

    def fire_due(self) -> None:
        now = time.time()
        for item in [d for d in self.due if d[0] <= now]:
            self.due.remove(item)
            f = item[1]
            if f.get("action") == "stop_modbus":
                # run_all.sh backgrounds the device scripts and supervisor has no stopasgroup, so
                # "stop modbus" alone leaves them serving (seen in the first S12): kill them too.
                sh("docker", "exec", "simulation", "supervisorctl", "stop", "modbus")
                sh("docker", "exec", "simulation", "pkill", "-f", IO_DEVICES, check=False)
                self.sc["stopped_modbus"] = True
                time.sleep(1)
                if sh("docker", "exec", "simulation", "pgrep", "-f", IO_DEVICES, check=False).strip():
                    raise EpisodeInvalid("comms-loss fault did not take: I/O device processes still running")
            else:
                state = faults.set_inputs(**f["set"])["state"]
                wrong = {k: state.get(k) for k, v in f["set"].items() if k in state and float(state[k]) != float(v)}
                if wrong:
                    raise EpisodeInvalid(f"fault did not take: {wrong}")
            self.log_event("fault", {**f, "t_vm": self.last_truth_t})

    # status ------------------------------------------------------------
    def status(self) -> dict:
        return json.loads(zs("status", self.sid, "--json"))

    def wait(self, pred, timeout_wall_s: float) -> dict:
        end = time.time() + timeout_wall_s
        while True:
            self.fire_due()
            st = self.status()
            if st["verdict"] in TERMINAL or pred(st) or time.time() > end:
                return st
            time.sleep(0.5)

    def mark(self, k: int) -> dict:
        """Declare step k and wait until ZeroState has registered it, before anyone acts on the plant:
        acting first leaves a gap where the monitor still holds the previous requirement (seen live:
        purge opened for the vent while still listed as blocked in -> "commanded state wrong")."""
        zs("step", "done", self.sid, str(k), "--by", "eval-operator")
        self.schedule(k, time.time())
        return self.wait(lambda st: st["steps"].get(str(k)) is not None, 30)

    def evaluated(self, k: int) -> dict:
        return self.wait(lambda st: evaluated(st, k), 900 / self.scale + 120)

    def log_event(self, kind, data):
        with open(self.out / "events.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.time(), "kind": kind, "data": data}) + "\n")

    def truth_logger(self):
        with open(self.out / "truth.jsonl", "a", encoding="utf-8") as fh, truth.stream(4) as samples:
            for d in samples:  # one reader inside the simulation container, VM-clock timestamps
                fh.write(json.dumps(d) + "\n")
                self.last_truth_t, self.last_pressure = d["t"], d["outputs"]["pressure"]
                if self.stop_truth.is_set():
                    return

    # run ------------------------------------------------------------------
    def run(self) -> dict:
        s = str(self.scale)
        pre = preflight()
        env = {**os.environ, "ZS_TIME_SCALE": s}
        subprocess.run([*COMPOSE, "up", "-d", "--force-recreate", "--no-deps", "simulation"], cwd=GRFICS, env=env,
                       check=True, capture_output=True)
        time.sleep(5)
        st = truth.read()["state"]
        if st.get("zs_patch_version") != "p1-1" or float(st.get("zs_time_scale")) != float(self.scale):
            raise EpisodeInvalid(f"simulator patch/scale wrong: {st.get('zs_patch_version')} x{st.get('zs_time_scale')}")
        self.warm_up()
        threading.Thread(target=self.truth_logger, daemon=True).start()
        plan_hash = self.plan.content_hash()
        self.session_started = True
        sh("docker", "exec", "-d", "-u", "zs", "zerostate", "zs", "session", "start",
           "--plan", "/app/config/p1_grfics/envelope.yaml", "--plan-hash", plan_hash, "--session", self.sid)
        time.sleep(1)
        st = self.wait(lambda st: st["state"] == "ready", 60)
        variant = self.sc.get("operator")
        for step in self.plan.steps:
            if st["verdict"] in TERMINAL or step.kind == "final":
                break
            k = step.k
            if step.kind == "vent_open" and (problem := vent_start_problem(self.last_pressure)):
                raise EpisodeInvalid(problem)
            self.schedule(k, None)  # faults tied to "before step k"
            st = self.mark(k)  # declare the step first, then act on the plant
            if st["verdict"] in TERMINAL:
                break
            if step.kind == "mode":
                if variant != "no_manual_mode":
                    act("manual", "on")
            elif step.kind in ("isolate", "vent_close"):
                for i, target in enumerate(step_targets(step)):  # e.g. block in: inlet first, then outlet
                    if variant == "wrong_valve_step2" and k == 2 and target == "f1":
                        target = "f2"
                    if i:
                        time.sleep(2)
                    act("set", target, str(step.required_state))
            elif step.kind == "vent_open":
                act("set", step.target, str(step.required_state))
            st = self.evaluated(k)
            if step.kind == "vent_open" and st["verdict"] not in TERMINAL:
                # keep venting until the plan's vent target (rolling mean); mark on regardless, like a hurried human
                act("wait-pressure-below", str(self.plan.vent_target_kpa_abs), "--mean-of", "8",
                         "--timeout-process-s", "900", "--process-time-scale", s)
                self.fire_due()
        if st["verdict"] not in TERMINAL:
            time.sleep(30 / self.scale)
        self.fire_due()
        zs("session", "stop", self.sid, "--by", "eval-runner")
        time.sleep(1)
        self.stop_truth.set()
        post = postflight(pre["ids_offset"], self.sc)
        final = self.status()
        (self.out / "audit_export.json").write_text(zs("audit", "export", self.sid), encoding="utf-8")
        sh("docker", "cp", f"zerostate:/data/runs/{self.sid}/signals.jsonl", str(self.out / "signals.jsonl"), check=False)
        result = {"scenario": self.sc["id"], "seed": self.seed, "expected": self.sc["expected"],
                  "verdict": final["verdict"], "match": final["verdict"] in self.sc["expected"],
                  "valid": post["valid"], "problems": post["problems"], "stamp": final["stamp"], "steps": final["steps"]}
        (self.out / "verdict.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        (self.out / "ids.json").write_text(json.dumps(post["ids"], indent=1), encoding="utf-8")
        return result

    def cleanup(self) -> None:
        """After a failed episode: leave nothing running and the plant back in AUTO."""
        if self.session_started:
            zs("session", "stop", self.sid, "--by", "eval-runner", check=False)
        self.stop_truth.set()
        if self.sc.get("stopped_modbus"):
            sh("docker", "exec", "simulation", "supervisorctl", "start", "modbus", check=False)
        try:
            faults.clear()
        except Exception as e:  # noqa: BLE001 - cleanup must reach the operator step even if this fails
            print(f"cleanup: faults.clear failed: {e}")
        operator("manual", "off")

    def warm_up(self, min_wall_s=120, steady_wall_s=30, timeout_wall_s=900):
        t0, steady_since = time.time(), None
        while time.time() - t0 < timeout_wall_s:
            p = truth.read()["outputs"]["pressure"]
            steady_since = (steady_since or time.time()) if abs(p - 2700) <= 54 else None
            if time.time() - t0 >= min_wall_s and steady_since and time.time() - steady_since >= steady_wall_s:
                return
            time.sleep(1)
        raise EpisodeInvalid("plant did not settle near 2700 kPa after the restart")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plant", default="p1", choices=["p1"])
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--seed", type=int, required=True)
    a = ap.parse_args()
    scenario = yaml.safe_load((ROOT / "eval" / "scenarios" / f"{a.scenario}.yaml").read_text(encoding="utf-8"))
    out = ROOT / "runs" / f"{a.scenario}_seed{a.seed}_{datetime.now(UTC):%Y%m%dT%H%M%S}"
    ep = Episode(scenario, a.seed, out)
    if problem := seed_problem(a.seed, ep.plan.content_hash()):
        raise SystemExit(problem)
    out.mkdir(parents=True)
    images = {n: sh("docker", "inspect", "--format", "{{.Image}}", n, check=False).strip()
              for n in ("simulation", "zerostate", "zs-operator", "plc")}
    (out / "meta.json").write_text(json.dumps({"scenario": scenario, "seed": a.seed, "faults": ep.faults,
                                               "process_time_scale": ep.scale, "images": images,
                                               "plan_hash": ep.plan.content_hash()}, indent=1), encoding="utf-8")
    try:
        result = ep.run()
    except EpisodeInvalid as e:
        ep.cleanup()
        result = {"scenario": a.scenario, "seed": a.seed, "valid": False, "problems": [str(e)]}
    except BaseException:
        ep.cleanup()
        raise
    (out / "verdict.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    publish(out)
    print(json.dumps(result, indent=1))
    return 0 if result.get("valid") and result.get("match") else 1


if __name__ == "__main__":
    raise SystemExit(main())
