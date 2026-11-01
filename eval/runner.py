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

from zerostate.models.envelope import IsolationPlan

ROOT = Path(__file__).parents[1]
GRFICS = ROOT.parent
P1 = ROOT / "plants" / "p1_grfics"
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", str(ROOT / "deploy" / "docker-compose.zerostate.yml")]
SOURCES = ("192.168.90.60", "192.168.90.70")
PLC = "192.168.95.2"
TERMINAL = ("BLOCKED", "ESCALATED")


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


def operator(*args) -> int:
    return subprocess.run(["docker", "exec", "zs-operator", "python", "operator.py", *args],
                          check=False, capture_output=True, text=True, timeout=1800).returncode


def draw(spec, rng: random.Random):
    """Scenario values: [lo, hi] floats/ints are drawn from the seed; anything else is used as is."""
    if isinstance(spec, list) and len(spec) == 2 and all(isinstance(x, (int, float)) for x in spec):
        lo, hi = spec
        return rng.randint(lo, hi) if all(isinstance(x, int) for x in spec) else rng.uniform(lo, hi)
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
        sh("docker", "exec", "simulation", "supervisorctl", "start", "modbus", check=False)
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

    # faults ------------------------------------------------------------
    def schedule(self, k: int, t_mark: float | None) -> None:
        for f in self.faults:
            if f.get("at_step") == k and (f.get("before_mark") if t_mark is None else not f.get("before_mark")):
                delay = 0.0 if t_mark is None else draw(f.get("after_process_s", [0, 0]), self.rng) / self.scale
                self.due.append(((t_mark or time.time()) + delay, f))
        self.fire_due()

    def fire_due(self) -> None:
        now = time.time()
        for item in [d for d in self.due if d[0] <= now]:
            self.due.remove(item)
            f = item[1]
            if f.get("action") == "stop_modbus":
                sh("docker", "exec", "simulation", "supervisorctl", "stop", "modbus")
                self.sc["stopped_modbus"] = True
            else:
                faults.set_inputs(**f["set"])
            self.log_event("fault", f)

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

    def mark_and_evaluate(self, k: int) -> dict:
        zs("step", "done", self.sid, str(k), "--by", "eval-operator")
        self.schedule(k, time.time())
        return self.wait(lambda st: st["steps"].get(k) not in (None, "pending"), 900 / self.scale + 120)

    def log_event(self, kind, data):
        with open(self.out / "events.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.time(), "kind": kind, "data": data}) + "\n")

    def truth_logger(self):
        with open(self.out / "truth.jsonl", "a", encoding="utf-8") as fh:
            while not self.stop_truth.is_set():
                t0 = time.time()
                try:
                    fh.write(json.dumps({"t": t0, **truth.read()}) + "\n")
                except OSError:
                    pass
                time.sleep(max(0.0, 0.25 - (time.time() - t0)))

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
        sh("docker", "exec", "-d", "-u", "zs", "zerostate", "zs", "session", "start",
           "--plan", "/app/config/p1_grfics/envelope.yaml", "--plan-hash", plan_hash, "--session", self.sid)
        time.sleep(1)
        st = self.wait(lambda st: st["state"] == "ready", 60)
        variant = self.sc.get("operator")
        for step in self.plan.steps:
            if st["verdict"] in TERMINAL or step.kind == "final":
                break
            k = step.k
            self.schedule(k, None)  # faults tied to "before step k"
            if step.kind == "mode":
                if variant != "no_manual_mode":
                    operator("manual", "on")
            elif step.kind in ("isolate", "vent_close"):
                target = "f2" if (variant == "wrong_valve_step2" and k == 2) else step.target
                operator("set", target, str(step.required_state))
            elif step.kind == "vent_open":
                operator("set", step.target, str(step.required_state))
            st = self.mark_and_evaluate(k)
            if step.kind == "vent_open" and st["verdict"] not in TERMINAL:
                # keep venting until the plan's vent target (rolling mean); mark on regardless, like a hurried human
                operator("wait-pressure-below", str(self.plan.vent_target_kpa_abs), "--mean-of", "8",
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
    if not 0 <= a.seed <= 999:
        raise SystemExit("Phase 1 uses tuning seeds 0-999 only")
    scenario = yaml.safe_load((ROOT / "eval" / "scenarios" / f"{a.scenario}.yaml").read_text(encoding="utf-8"))
    out = ROOT / "runs" / f"{a.scenario}_seed{a.seed}_{datetime.now(UTC):%Y%m%dT%H%M%S}"
    out.mkdir(parents=True)
    images = {n: sh("docker", "inspect", "--format", "{{.Image}}", n, check=False).strip()
              for n in ("simulation", "zerostate", "zs-operator", "plc")}
    ep = Episode(scenario, a.seed, out)
    (out / "meta.json").write_text(json.dumps({"scenario": scenario, "seed": a.seed, "faults": ep.faults,
                                               "process_time_scale": ep.scale, "images": images,
                                               "plan_hash": ep.plan.content_hash()}, indent=1), encoding="utf-8")
    try:
        result = ep.run()
    except EpisodeInvalid as e:
        result = {"scenario": a.scenario, "seed": a.seed, "valid": False, "problems": [str(e)]}
        (out / "verdict.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0 if result.get("valid") and result.get("match") else 1


if __name__ == "__main__":
    raise SystemExit(main())
