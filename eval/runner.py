"""Episode runner (host), P1 and P2. One episode = one scenario at one seed, end to end:

preflight (router + IDS rules, noise floor off, IDS log offset, operator in AUTO) -> recreate the
patched simulator -> warm up -> ZeroState session -> operator performs each plan step, marked only
after the previous step is evaluated -> scenario fault at its seeded onset -> stop at a terminal
verdict or after the hold -> postflight (rules still there, IDS: 0 ZeroState writes and > 0
operator writes). Episodes are pre-registered by seed and replayable from logs.

    python eval/runner.py --plant p1 --scenario S0 --seed 7
    python eval/runner.py --plant p2 --scenario S0 --seed 7   (P2Episode: OPC UA gas line, see below)
"""

import argparse
import importlib.util
import inspect
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
P2 = ROOT / "plants" / "p2_gasline"
P2_HOST, P2_PORT, P2_CONTAINER = "192.168.95.50", 4840, "zs-p2"
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", str(ROOT / "deploy" / "docker-compose.zerostate.yml")]
SOURCES = ("192.168.90.60", "192.168.90.70")
PLC = "192.168.95.2"
TERMINAL = ("BLOCKED", "ESCALATED")
IO_DEVICES = "python (feed1|feed2|purge|product|tank|analyzer).py"  # GRFICS remote I/O device scripts
MIN_VENT_START_KPA = 1500  # below this the vent rules get too little range to judge: episode INVALID
TUNING_SEEDS = range(1000)  # anything else is a scoring seed
# Hash of each plant's committed benchmark plan (plan digests, not secrets). None = no plan confirmed by
# the owner yet: scoring seeds on that plant are refused. The owner fills these in after confirming.
BENCHMARK_PLAN_HASH = {
    # pending owner confirmation: 63e1519c52f653b2607444e39baa63973b27cd867ec45c056d017f26e5f1bbc4 (envelope + camera: optional)  # pragma: allowlist secret
    "p1": "89adfcf4fbb0a8e2b058c02ceed5d879d0a72312da92024bf967c8aec14f2a92",  # pragma: allowlist secret
    "p2": None,
}


def _load(name, folder=P1):
    spec = importlib.util.spec_from_file_location(name, folder / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


faults, truth, seal = _load("faults"), _load("truth"), _load("seal", ROOT / "eval")
# What the zerostate image holds (deploy/Dockerfile), as (key prefix, path in the image, path here, glob).
CODE_SPEC = [*[("src/", "src/zerostate", "src/zerostate", f"**/*.{ext}") for ext in ("py", "yaml", "md")],
             *[("config/", "config/p1_grfics", "plants/p1_grfics", f) for f in ("modbus_map.yaml", "envelope.yaml", "thresholds.yaml")],
             ("config/frame_service/", "config/frame_service", "plants/frame_service", "display_map.yaml")]
# P2: same product code, P2 config (the image copies plants/p2_gasline/*.yaml to config/p2_gasline).
CODE_SPEC_P2 = [*CODE_SPEC[:3], *[("config/p2_gasline/", "config/p2_gasline", "plants/p2_gasline", f)
                                  for f in ("opcua_map.yaml", "plant_map.yaml", "isolation_list.yaml", "thresholds.yaml")]]
FRAMES_URL = "http://172.30.0.3:8080"  # zs-frames on zs-internal, as ZeroState sees it
FIRST_FRAME = ("import urllib.request as u; r = u.urlopen('http://localhost:8080/frame?view=default', timeout=100); "
               "print('ok' if r.read(2) == b'\\xff\\xd8' else 'bad')")


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


def seed_problem(seed: int, plan_hash: str, plant: str = "p1") -> str | None:
    """Scoring seeds run only on the plant's committed benchmark plan, so a benchmark never mixes plans."""
    if seed < 0:
        return "seed must be >= 0"
    if seed in TUNING_SEEDS:
        return None
    want = BENCHMARK_PLAN_HASH.get(plant)
    if want is None:
        return f"scoring seed {seed} refused: no benchmark plan confirmed for {plant} yet (BENCHMARK_PLAN_HASH[{plant!r}] is None)"
    if plan_hash != want:
        return f"scoring seed {seed} refused: plan hash {plan_hash[:12]} is not the {plant} benchmark plan {want[:12]}"
    return None


def git(*args) -> tuple[int, str]:
    r = subprocess.run(["git", *args], check=False, capture_output=True, text=True, timeout=60, cwd=ROOT)
    return r.returncode, r.stdout.strip()


def scoring_problem(batch: str | None, manifest_p, salt_p, scenario: str, seed: int, plant: str = "p1") -> str | None:
    """A scoring seed runs only from its sealed batch, on that batch's frozen tag, with nothing edited."""
    if not (batch and manifest_p and salt_p):
        return f"scoring seed {seed} needs --batch, --manifest and --salt"
    manifest, h = seal.load(manifest_p, salt_p)
    sealed = ROOT / "eval" / f"sealed_hash_{batch}.txt"
    if not sealed.exists() or sealed.read_text(encoding="utf-8").strip() != h:
        return f"manifest and salt do not match eval/sealed_hash_{batch}.txt"
    if {"plant": plant, "scenario": scenario, "seed": seed} not in manifest["entries"]:
        return f"{scenario} seed {seed} is not in the sealed {batch} manifest"
    rc, tag = git("rev-parse", f"refs/tags/bench-freeze-{batch}^{{commit}}")
    head = git("rev-parse", "HEAD")[1]
    if rc != 0 or head != tag:
        return f"HEAD {head[:12]} is not bench-freeze-{batch}"
    if git("diff", "--quiet", "HEAD")[0] != 0:
        return "tracked files differ from the frozen tag"
    return None


def fingerprint(spec) -> dict:
    """sha256 per file, line endings normalised. Runs here and, sent as source, inside the container."""
    import hashlib
    import pathlib
    out = {}
    for prefix, root, pattern in spec:
        for p in sorted(pathlib.Path(root).glob(pattern)):
            if "__pycache__" not in p.parts:
                out[prefix + p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return out


def code_problem(code_spec=CODE_SPEC) -> str | None:
    """The running zerostate image must hold exactly this tree's product code and the plant's config."""
    here = fingerprint([(pre, str(ROOT / local), pat) for pre, _, local, pat in code_spec])
    spec = [(pre, img, pat) for pre, img, _, pat in code_spec]
    script = inspect.getsource(fingerprint) + f"\nimport json\nprint(json.dumps(fingerprint({spec!r})))\n"
    r = subprocess.run(["docker", "exec", "-i", "-w", "/app", "zerostate", "python", "-"], input=script,
                       check=False, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return f"could not fingerprint the zerostate container: {r.stderr.strip()[:200]}"
    there = json.loads(r.stdout)
    diff = sorted(k for k in here.keys() | there.keys() if here.get(k) != there.get(k))
    return f"zerostate container code differs from this tree: {diff[:5]}" if diff else None


def add_signals_hash(out: Path) -> str | None:
    """meta.json gets the SHA-256 of the full local signals.jsonl (None when the copy failed), so a
    published episode can be tied to the signals it was judged on."""
    import hashlib
    sig = out / "signals.jsonl"
    h = hashlib.sha256(sig.read_bytes()).hexdigest() if sig.exists() else None
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    (out / "meta.json").write_text(json.dumps({**meta, "signals_sha256": h}, indent=1), encoding="utf-8")
    return h


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
def router_rules_ok(targets=((PLC, 502),)) -> bool:
    """Each source's allow rules (P1: PLC:502; P2 also adds P2:4840) sit above its drop, above the allow-all."""
    chain = sh("docker", "exec", "router", "iptables", "-S", "FORWARD").splitlines()
    i_all = chain.index("-A FORWARD -j ACCEPT") if "-A FORWARD -j ACCEPT" in chain else len(chain)
    for src in SOURCES:
        drop = f"-A FORWARD -s {src}/32 -j DROP"
        for host, port in targets:
            allow = f"-A FORWARD -s {src}/32 -d {host}/32 -p tcp -m tcp --dport {port} -j ACCEPT"
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


def publish(run: Path, results: Path = ROOT / "eval" / "results" / "episodes") -> Path:
    """Copy what anyone needs to replay and score an episode into eval/results/ (committed; scoring
    episodes go to bench/<batch>/); truth is gzipped. signals.jsonl stays in runs/ (it is the same data
    the audit windows carry)."""
    import gzip
    import shutil
    dest = results / run.name
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
    def __init__(self, scenario: dict, seed: int, out: Path, scoring: bool = False, camera: bool = False):
        self.sc, self.seed, self.out, self.scoring, self.camera = scenario, seed, out, scoring, camera
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

    def reopen_test(self, j: int) -> dict:
        """S13 inch and test: reopen step j (declared first), open its first point a little, close it
        again and re-mark the step, but nobody verifies it again."""
        step = next(s for s in self.plan.steps if s.k == j)
        target = step_targets(step)[0]
        zs("step", "reopen", self.sid, str(j), "--by", "eval-operator", "--reason", f"inch and test {target}")
        self.wait(lambda st: str(j) not in st["steps"], 30)
        act("set", target, "20")
        time.sleep(10 / self.scale + 2)
        self.mark(j)
        for t in step_targets(step):
            act("set", t, str(step.required_state))
        return self.evaluated(j)

    def frames_ready(self, timeout_wall_s: float = 300) -> None:
        """After a simulator recreate the frame service's page points at a dead scene: restart it and wait
        for its first frame (the page load takes views.yaml's load_wait_s)."""
        sh("docker", "restart", "zs-frames")
        end = time.time() + timeout_wall_s
        while time.time() < end:
            if sh("docker", "exec", "zs-frames", "python", "-c", FIRST_FRAME, check=False, timeout=150).strip() == "ok":
                return
            time.sleep(5)
        raise EpisodeInvalid("frame service gave no frame after the simulator restart")

    def camera_settled(self, timeout_wall_s: float = 180) -> None:
        """Before stop: let every started camera burst be read and evaluated (a timeout leaves it pending)."""
        end = time.time() + timeout_wall_s
        while self.status().get("camera_pending", 0) > 0 and time.time() < end:
            self.fire_due()
            time.sleep(1)

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
        if self.scoring and (problem := code_problem()):
            raise EpisodeInvalid(problem)
        pre = preflight()
        env = {**os.environ, "ZS_TIME_SCALE": s}
        subprocess.run([*COMPOSE, "up", "-d", "--force-recreate", "--no-deps", "simulation"], cwd=GRFICS, env=env,
                       check=True, capture_output=True)
        time.sleep(5)
        st = truth.read()["state"]
        if st.get("zs_patch_version") != "p1-1" or float(st.get("zs_time_scale")) != float(self.scale):
            raise EpisodeInvalid(f"simulator patch/scale wrong: {st.get('zs_patch_version')} x{st.get('zs_time_scale')}")
        self.warm_up()
        if self.camera:
            self.frames_ready()
        threading.Thread(target=self.truth_logger, daemon=True).start()
        plan_hash = self.plan.content_hash()
        self.session_started = True
        cam_env = ["-e", f"ZS_FRAMES_URL={FRAMES_URL}"] if self.camera else []
        sh("docker", "exec", "-d", "-u", "zs", *cam_env, "zerostate", "zs", "session", "start",
           "--plan", "/app/config/p1_grfics/envelope.yaml", "--plan-hash", plan_hash, "--session", self.sid)
        time.sleep(1)
        st = self.wait(lambda st: st["state"] == "ready", 60)
        variant = self.sc.get("operator")
        for step in self.plan.steps:
            if st["verdict"] in TERMINAL or step.kind == "final":
                break
            k = step.k
            if variant == "skip_step" and k == self.sc["skip_step"]:
                continue  # S7: a hurried operator skips step k and marks k+1 right after k-1's evaluation
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
            if step.kind == "isolate" and st["verdict"] not in TERMINAL:  # a second person checks it (PROC-INDEPENDENCE)
                zs("step", "verify", self.sid, str(k), "--by", "eval-operator" if variant == "same_verifier" else "eval-verifier")
            if variant == "reopen_test" and k == self.sc["reopen_after"] and st["verdict"] not in TERMINAL:
                st = self.reopen_test(self.sc["reopen_step"])
            if step.kind == "vent_open" and st["verdict"] not in TERMINAL:
                # keep venting until the plan's vent target (rolling mean); mark on regardless, like a hurried human
                act("wait-pressure-below", str(self.plan.vent_target_kpa_abs), "--mean-of", "8",
                         "--timeout-process-s", "900", "--process-time-scale", s)
                self.fire_due()
        if st["verdict"] not in TERMINAL:
            time.sleep(30 / self.scale)
        self.fire_due()
        if self.camera:
            self.camera_settled()
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
        if self.camera:  # the with-camera track, reported separately (idealised camera on P1)
            result |= {"verdict_with_camera": final.get("verdict_with_camera"), "camera_pending": final.get("camera_pending")}
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


# ---------------------------------------------------------------- P2 (OPC UA gas line)
P2_TARGETS = ((PLC, 502), (P2_HOST, P2_PORT))
P2_MIN_VENT_START_KPA = 1500  # F-210 starts at S-200's 2000 kPa
P2_CONFIG = "/app/config/p2_gasline"
P2_ENV = ["-e", f"ZS_MAP={P2_CONFIG}/opcua_map.yaml", "-e", f"ZS_THRESHOLDS={P2_CONFIG}/thresholds.yaml"]


P2_SECRETS = ("P2_PASSWORD_ZEROSTATE", "P2_PASSWORD_OPERATOR")


def p2_env(env_file: Path = ROOT / ".env") -> dict:
    """os.environ plus the P2 passwords from zerostate/.env when the shell lacks them (one source for
    the server, ZeroState and the operator). Values are passed on, never printed or logged."""
    env = dict(os.environ)
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and k in P2_SECRETS and not env.get(k):
                env[k] = v.strip().strip('"').strip("'")
    return env


def operator_p2(*args) -> int:
    """The P2 operator (plants/p2_gasline/operator.py, in zs-operator as operator_p2.py): OPC UA as `operator`.
    `-e NAME` without a value hands the password over from this process's environment, off the command line."""
    return subprocess.run(["docker", "exec", "-e", "P2_PASSWORD_OPERATOR", "zs-operator", "python", "operator_p2.py", *args],
                          check=False, capture_output=True, text=True, timeout=1800, env=p2_env()).returncode


def act_p2(*args) -> None:
    rc = operator_p2(*args)
    if rc not in (0, 2) or (rc == 2 and args[0] != "wait-pressure-below"):
        raise EpisodeInvalid(f"operator_p2 {' '.join(args)} failed (exit {rc})")


def p2_plan() -> IsolationPlan:
    """P2's plan = its plant map merged with its isolation list (what the owner confirms)."""
    from zerostate.graph.build import merge
    from zerostate.models.envelope import IsolationList
    from zerostate.models.plant_map import PlantMap
    m = PlantMap.model_validate(yaml.safe_load((P2 / "plant_map.yaml").read_text(encoding="utf-8")))
    plan, problems = merge(m, IsolationList.model_validate(yaml.safe_load((P2 / "isolation_list.yaml").read_text(encoding="utf-8"))))
    if plan is None:
        raise SystemExit(f"P2 isolation list does not merge: {problems}")
    return plan


def p2_writes(log_text: str) -> dict:
    """The P2 server logs every write attempt with its user: ZeroState's must stay 0, the operator's > 0."""
    rows = [json.loads(line) for line in log_text.splitlines() if line.strip()]
    return {"zerostate": sum(r["user"] == "zerostate" for r in rows),
            "operator_allowed": sum(r["user"] == "operator" and r["allowed"] for r in rows),
            "other": sum(r["user"] not in ("zerostate", "operator") for r in rows)}


def p2_vent_wait(plan: IsolationPlan, step, first_vent_k: int) -> tuple[str, float]:
    """(gauge, kPa) the operator vents to: BV-202 bleeds the cavity (PT-202) to the vent target; the first
    VV-213 vent takes F-210 (PT-211) to the hold pressure, the final one to the vent target."""
    if step.target == "BV-202":
        return "PT-202", plan.vent_target_kpa_abs
    return "PT-211", plan.hold_pressure_kpa_abs if step.k == first_vent_k else plan.vent_target_kpa_abs


class P2Episode(Episode):
    """P2 gas line: the zs-p2 OPC UA server is recreated per episode (compose profile p2), faults and
    truth go through its unix socket (plants/p2_gasline/faults.py, truth.py), the operator writes *.CMD
    over OPC UA, and the server's own write log takes the IDS's place. P1's Episode is left as it ran."""

    def __init__(self, scenario: dict, seed: int, out: Path, scoring: bool = False, camera: bool = False):
        if camera:
            raise SystemExit("P2 has no camera")
        self.sc, self.seed, self.out, self.scoring, self.camera = scenario, seed, out, scoring, False
        self.rng = random.Random(seed)
        self.faults = [draw(f, self.rng) for f in scenario.get("faults", [])]
        self.plan = p2_plan()
        self.plan_path = None
        self.scale = yaml.safe_load((P2 / "opcua_map.yaml").read_text(encoding="utf-8"))["process_time_scale"]
        self.sid = out.name
        self.due: list[tuple[float, dict]] = []
        self.stop_truth = threading.Event()
        self.last_truth_t = None
        self.last_pressure = None
        self.session_started = False
        self.p2faults = _load("faults", P2)
        self.p2truth = None  # loaded after the container is up (its import puts plants/p2_gasline on sys.path)

    def fire_due(self) -> None:
        now = time.time()
        for item in [d for d in self.due if d[0] <= now]:
            self.due.remove(item)
            f = item[1]
            try:
                if f.get("action") == "stop_updates":
                    self.p2faults.updates(False)
                else:
                    self.p2faults.set_inputs(**f["set"])
            except (RuntimeError, subprocess.SubprocessError, ValueError) as e:
                raise EpisodeInvalid(f"fault did not take: {e}") from e
            self.log_event("fault", {**f, "t_vm": self.last_truth_t})

    def truth_logger(self):
        with open(self.out / "truth.jsonl", "a", encoding="utf-8") as fh, self.p2truth.stream(4) as samples:
            for d in samples:
                fh.write(json.dumps(d) + "\n")
                self.last_truth_t, self.last_pressure = d["t"], d["pressure_kpa_abs"]["F-210"]
                if self.stop_truth.is_set():
                    return

    def warm_up(self, timeout_wall_s=120):
        """A fresh server starts at S-200's pressure; wait until it answers and publishes."""
        end = time.time() + timeout_wall_s
        while time.time() < end:
            try:
                d = self.p2faults.read()
                if d.get("updating") and float(d.get("time_scale")) == float(self.scale) and d["pressure_kpa_abs"]["F-210"] > P2_MIN_VENT_START_KPA:
                    return
            except (RuntimeError, subprocess.SubprocessError, ValueError, KeyError):
                pass
            time.sleep(2)
        raise EpisodeInvalid(f"P2 server not ready (updating at x{self.scale}, F-210 above {P2_MIN_VENT_START_KPA} kPa)")

    def preflight(self) -> None:
        if not router_rules_ok(P2_TARGETS):
            raise EpisodeInvalid("router rules for .60/.70 -> P2:4840 missing or below the allow-all: run apply_router_rules.ps1")

    def postflight(self) -> dict:
        self.p2faults.clear()
        writes = p2_writes(sh("docker", "exec", P2_CONTAINER, "sh", "-c", "cat /var/log/p2_writes.jsonl 2>/dev/null || true"))
        problems = []
        if not router_rules_ok(P2_TARGETS):
            problems.append("router rules changed during the episode")
        if writes["zerostate"] or writes["other"]:
            problems.append(f"OPC UA write attempts not by the operator: {writes}")
        if writes["operator_allowed"] == 0:
            problems.append("operator writes not in the P2 write log (log or permissions broken)")
        return {"ids": {"p2_writes": writes}, "valid": not problems, "problems": problems}

    def run(self) -> dict:
        s = str(self.scale)
        if self.scoring and (problem := code_problem(CODE_SPEC_P2)):
            raise EpisodeInvalid(problem)
        self.preflight()
        r = subprocess.run([*COMPOSE, "--profile", "p2", "up", "-d", "--force-recreate", "--no-deps", "p2"], cwd=GRFICS,
                           env={**p2_env(), "ZS_P2_TIME_SCALE": s}, check=False, capture_output=True, text=True)
        if r.returncode != 0:
            raise EpisodeInvalid(f"could not start zs-p2: {r.stderr.strip()[:300]}")
        self.warm_up()
        self.p2truth = _load("truth", P2)
        threading.Thread(target=self.truth_logger, daemon=True).start()
        plan_hash = self.plan.content_hash()
        self.session_started = True
        # the owner-confirmed P2 plan is /data/plans/<hash>.json (zs plan confirm stores it there)
        sh("docker", "exec", "-d", "-u", "zs", *P2_ENV, "zerostate", "zs", "session", "start",
           "--plan", f"/data/plans/{plan_hash}.json", "--plan-hash", plan_hash, "--session", self.sid)
        time.sleep(1)
        st = self.wait(lambda st: st["state"] == "ready", 60)
        variant = self.sc.get("operator")
        vents = [x.k for x in self.plan.steps if x.kind == "vent_open" and x.target != "BV-202"]
        for step in self.plan.steps:
            if st["verdict"] in TERMINAL or step.kind == "final":
                break
            k = step.k
            if variant == "skip_step" and k == self.sc["skip_step"]:
                continue
            if step.kind == "vent_open" and vents and k == vents[0] and (
                    self.last_pressure is None or self.last_pressure < P2_MIN_VENT_START_KPA):
                raise EpisodeInvalid(f"vent start {self.last_pressure} kPa below {P2_MIN_VENT_START_KPA}")
            self.schedule(k, None)
            st = self.mark(k)
            if st["verdict"] in TERMINAL:
                break
            if step.kind in ("isolate", "vent_close", "vent_open"):
                for i, target in enumerate(step_targets(step)):
                    if variant == "wrong_valve_step4" and k == 4 and target == "XV-204":
                        target = "XV-231"  # S5: the adjacent line's block
                    if i:
                        time.sleep(2)
                    act_p2("set", target, str(step.required_state))
            st = self.evaluated(k)
            if step.kind == "isolate" and st["verdict"] not in TERMINAL:
                zs("step", "verify", self.sid, str(k), "--by", "eval-operator" if variant == "same_verifier" else "eval-verifier")
            if step.kind == "vent_open" and st["verdict"] not in TERMINAL:
                gauge, kpa = p2_vent_wait(self.plan, step, vents[0] if vents else -1)
                act_p2("wait-pressure-below", gauge, str(kpa), "--mean-of", "8",
                       "--timeout-process-s", "900", "--process-time-scale", s)
                self.fire_due()
        if st["verdict"] not in TERMINAL:
            time.sleep(30 / self.scale)
        self.fire_due()
        zs("session", "stop", self.sid, "--by", "eval-runner")
        time.sleep(1)
        self.stop_truth.set()
        post = self.postflight()
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
        if self.session_started:
            zs("session", "stop", self.sid, "--by", "eval-runner", check=False)
        self.stop_truth.set()
        try:
            self.p2faults.clear()  # also turns the update loop back on (S12)
        except Exception as e:  # noqa: BLE001 - cleanup must not raise over the original failure
            print(f"cleanup: P2 faults.clear failed: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plant", default="p1", choices=["p1", "p2"])
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--batch", help="sealed batch (scoring seeds only), e.g. p1")
    ap.add_argument("--manifest", help="sealed manifest, kept outside the repo")
    ap.add_argument("--salt", help="sealed salt, kept outside the repo")
    ap.add_argument("--camera", action="store_true",
                    help="zs-frames in use: restart it after each simulator recreate, pass ZS_FRAMES_URL, wait for camera reads")
    a = ap.parse_args()
    scen_dir = ROOT / "eval" / "scenarios" / ("p2" if a.plant == "p2" else "")
    scenario = yaml.safe_load((scen_dir / f"{a.scenario}.yaml").read_text(encoding="utf-8"))
    out = ROOT / "runs" / f"{a.scenario}_seed{a.seed}_{datetime.now(UTC):%Y%m%dT%H%M%S}"
    scoring = a.seed not in TUNING_SEEDS
    ep = (P2Episode if a.plant == "p2" else Episode)(scenario, a.seed, out, scoring, camera=a.camera)
    problem = seed_problem(a.seed, ep.plan.content_hash(), a.plant)
    if scoring and not problem:
        problem = scoring_problem(a.batch, a.manifest, a.salt, a.scenario, a.seed, a.plant)
    if problem:
        raise SystemExit(problem)
    out.mkdir(parents=True)
    images = {n: sh("docker", "inspect", "--format", "{{.Image}}", n, check=False).strip()
              for n in ((P2_CONTAINER, "zerostate", "zs-operator") if a.plant == "p2" else
                        ("simulation", "zerostate", "zs-operator", "plc", *(["zs-frames"] if a.camera else [])))}
    (out / "meta.json").write_text(json.dumps({"scenario": scenario, "seed": a.seed, "faults": ep.faults,
                                               "process_time_scale": ep.scale, "images": images,
                                               "plan_hash": ep.plan.content_hash(), "batch": a.batch if scoring else None,
                                               "camera": a.camera},
                                              indent=1), encoding="utf-8")
    try:
        result = ep.run()
    except EpisodeInvalid as e:
        ep.cleanup()
        result = {"scenario": a.scenario, "seed": a.seed, "valid": False, "problems": [str(e)]}
    except BaseException:
        ep.cleanup()
        raise
    (out / "verdict.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    add_signals_hash(out)
    publish(out, ROOT / "eval" / "results" / "bench" / a.batch if scoring else ROOT / "eval" / "results" / "episodes")
    print(json.dumps(result, indent=1))
    return 0 if result.get("valid") and result.get("match") else 1


if __name__ == "__main__":
    raise SystemExit(main())
