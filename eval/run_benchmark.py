"""Run a sealed batch: every manifest entry, in sealed order, through eval/runner.py. Run it from the
worktree checked out at the batch tag (the runner refuses scoring seeds anywhere else).

    python eval/run_benchmark.py --batch p1 --manifest D:/grfics/sealed/manifest_p1.json --salt D:/grfics/sealed/salt_p1

Resumable: an entry with a valid result, or with two INVALID attempts, is not run again. An INVALID
episode is retried once with the same seed; the INVALID rate is reported. Three INVALIDs in a row stop
the batch (a lab fault, e.g. router rules wiped by a Docker restart): fix it, then run the same command.
Watchdog: from 05:00, if the batch would finish after 09:00, S0 entries beyond 10 valid are skipped;
--no-watchdog turns that off (batch 2: S0 x15 stays whole). --first N runs only the first N entries in
sealed order (batch p2: N fixed before launch, logged, and the same N required on resume).
--invalidate-unfired logs an `invalidated` record for every valid attempt whose drawn fault never fired
(the runner's rule since batch p2's S2, DECISIONS Nov 4), so those entries run again; the record is
appended, nothing is rewritten.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
MAX_ATTEMPTS = 2
RUNNER_PLANTS = ("p1", "p2")  # "plan" entries (the plan-check set) are run by eval/plan_benchmark.py
STOP_AFTER_INVALID_IN_A_ROW = 3
WATCHDOG_FROM_HOUR, WATCHDOG_FINISH_BY_HOUR, WATCHDOG_KEEP_S0 = 5, 9, 10


def key(e: dict) -> tuple:
    return e.get("plant"), e.get("scenario"), e.get("seed")  # .get: progress also holds a first_n record


def read_progress(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def invalidated(progress: list[dict]) -> set[str]:
    return {p["episode"] for p in progress if p.get("kind") == "invalidated"}


def counts(p: dict, inv: set[str]) -> bool:
    """A valid attempt, not invalidated afterwards."""
    return bool(p["valid"]) and p.get("episode") not in inv


def done(entry: dict, progress: list[dict]) -> bool:
    tries = [p for p in progress if key(p) == key(entry) and p.get("kind") == "attempt"]
    skipped = any(key(p) == key(entry) and p.get("kind") == "skipped" for p in progress)
    inv = invalidated(progress)
    return skipped or any(counts(t, inv) for t in tries) or len(tries) >= MAX_ATTEMPTS


def unfired(runs: Path, attempt: dict) -> str | None:
    """The runner's rule (runner.P2Episode.unfired) on an attempt already run: a drawn fault with no fault
    event, unless the verdict blocked or escalated first (the fault's step never came)."""
    d = runs / attempt["episode"]
    drawn = json.loads((d / "meta.json").read_text(encoding="utf-8")).get("faults") or []
    ev = d / "events.jsonl"
    fired = sum(json.loads(x).get("kind") == "fault" for x in ev.read_text(encoding="utf-8").splitlines() if x.strip()) if ev.exists() else 0
    if attempt["valid"] and len(drawn) > fired and attempt.get("verdict") not in ("BLOCKED", "ESCALATED"):
        return f"drawn fault never fired: {len(drawn)} drawn, {fired} fault events, verdict {attempt.get('verdict')}"
    return None


def watchdog_skip(entry: dict, now: datetime, remaining: int, mean_wall_s: float | None, s0_valid: int) -> bool:
    """Skip an S0 beyond the 10th valid one when, from 05:00, the batch would end after 09:00."""
    if entry["scenario"] != "S0" or s0_valid < WATCHDOG_KEEP_S0 or mean_wall_s is None:
        return False
    if not WATCHDOG_FROM_HOUR <= now.hour < 12:  # the batch starts in the evening: only the morning counts
        return False
    deadline = now.replace(hour=WATCHDOG_FINISH_BY_HOUR, minute=0, second=0, microsecond=0)
    return now.timestamp() + remaining * mean_wall_s > deadline.timestamp()


def run_episode(entry: dict, a) -> dict:
    """One runner call. Returns the runner's verdict.json, or None when the runner refused to start."""
    before = set((ROOT / "runs").glob(f"{entry['scenario']}_seed{entry['seed']}_*"))
    subprocess.run([sys.executable, "-P", str(ROOT / "eval" / "runner.py"), "--plant", entry["plant"],
                    "--scenario", entry["scenario"], "--seed", str(entry["seed"]), "--batch", a.batch,
                    "--manifest", a.manifest, "--salt", a.salt, *(["--camera"] if getattr(a, "camera", False) else [])],
                   check=False, cwd=ROOT)
    new = sorted(set((ROOT / "runs").glob(f"{entry['scenario']}_seed{entry['seed']}_*")) - before)
    if not new or not (new[-1] / "verdict.json").exists():
        return None
    return {"episode": new[-1].name, **json.loads((new[-1] / "verdict.json").read_text(encoding="utf-8"))}


P2_NET_TESTS = "test_p2_opcua_reachable or test_zerostate_account_cannot_write_p2"
P2_MIN_FIRST_N = 30  # DECISIONS Nov 3: below 30, P2 is a no-go


def p2_net_gate() -> tuple[bool, str]:
    """The two live-P2 network tests, inside zerostate with P2 up: 4840 reachable through the allowlist, and
    ZeroState's own OPC UA account refused on a write with the value unchanged. Both must PASS (a skip fails)."""
    r = subprocess.run(["docker", "exec", "-e", "ZS_NET_P2=1", "-u", "zs", "zerostate", "pytest", "-m", "net", "-q", "-rA",
                        "-p", "no:cacheprovider", "tests/net/test_container_isolation.py", "-k", P2_NET_TESTS],
                       capture_output=True, text=True, timeout=300, check=False)
    tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or ["no output"]
    return r.returncode == 0 and "2 passed" in tail[0] and "skipped" not in tail[0], tail[0]


def run_batch(manifest: dict, progress_p: Path, a, run=run_episode, clock=datetime.now, net_gate=p2_net_gate) -> int:
    progress_p.parent.mkdir(parents=True, exist_ok=True)

    def log(rec):
        with open(progress_p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": clock().isoformat(), **rec}) + "\n")

    entries, in_a_row = manifest["entries"], 0
    if getattr(a, "invalidate_unfired", False):
        progress = read_progress(progress_p)
        inv = invalidated(progress)
        for p in progress:
            if p.get("kind") == "attempt" and p.get("episode") not in inv and (why := unfired(ROOT / "runs", p)):
                log({"kind": "invalidated", **{k: p[k] for k in ("plant", "scenario", "seed", "episode")}, "reason": why})
    if any(e.get("plant") == "p2" for e in entries):  # hard gate, on every launch and resume (DECISIONS Nov 4)
        if (getattr(a, "first", None) or 0) < P2_MIN_FIRST_N:
            print(f"batch with P2 entries needs --first N >= {P2_MIN_FIRST_N}, fixed before launch")
            return 2
        ok, detail = net_gate()
        log({"kind": "p2_net_gate", "passed": ok, "detail": detail})
        if not ok:
            print(f"P2 network gate failed ({detail}): batch p2 does not launch")
            return 2
    first_n = getattr(a, "first", None)
    logged = [p["n"] for p in read_progress(progress_p) if p.get("kind") == "first_n"]
    if logged and logged[0] != first_n:  # N is fixed before launch: a resume can't change it or drop it
        print(f"--first {first_n} refused: this batch was launched with --first {logged[0]}")
        return 2
    if first_n is not None:
        if not logged:
            if any(p.get("kind") == "attempt" for p in read_progress(progress_p)):
                print("--first refused: this batch already ran without it")
                return 2
            log({"kind": "first_n", "n": first_n})
        entries = entries[:first_n]
    for i, e in enumerate(entries):
        progress = read_progress(progress_p)
        if done(e, progress):
            continue
        attempts = [p for p in progress if p.get("kind") == "attempt"]
        durations = [p["wall_s"] for p in attempts if "wall_s" in p]
        mean = sum(durations) / len(durations) if durations else None
        s0_valid = sum(1 for p in attempts if p["scenario"] == "S0" and p["valid"])
        remaining = sum(1 for x in entries[i:] if not done(x, progress))
        if not getattr(a, "no_watchdog", False) and watchdog_skip(e, clock(), remaining, mean, s0_valid):
            log({"kind": "skipped", **e, "reason": f"watchdog: {s0_valid} valid S0, projected finish after 0{WATCHDOG_FINISH_BY_HOUR}:00"})
            continue
        while not done(e, read_progress(progress_p)):
            t0 = time.monotonic()
            r = run(e, a)
            if r is None:
                log({"kind": "refused", **e})
                print(f"runner refused {e}: fix the setup (tag, seal, plan), then re-run this command")
                return 2
            valid = bool(r.get("valid"))
            log({"kind": "attempt", **e, "valid": valid, "match": r.get("match"), "verdict": r.get("verdict"),
                 "episode": r.get("episode"), "problems": r.get("problems", []), "wall_s": round(time.monotonic() - t0)})
            in_a_row = 0 if valid else in_a_row + 1
            if in_a_row >= STOP_AFTER_INVALID_IN_A_ROW:
                print(f"{in_a_row} INVALID episodes in a row: stopping. Last problems: {r.get('problems')}")
                return 3
    summary({**manifest, "entries": entries}, read_progress(progress_p))
    return 0


def summary(manifest: dict, progress: list[dict]) -> dict:
    attempts, inv = [p for p in progress if p.get("kind") == "attempt"], invalidated(progress)
    entries = manifest["entries"]
    valid = sum(1 for e in entries if any(key(p) == key(e) and counts(p, inv) for p in attempts))
    skipped = sum(1 for e in entries if any(key(p) == key(e) and p.get("kind") == "skipped" for p in progress))
    out = {"entries": len(entries), "valid": valid, "invalid": len(entries) - valid - skipped, "skipped": skipped,
           "attempts": len(attempts), "invalid_attempts": sum(1 for p in attempts if not counts(p, inv))}
    out["invalid_rate"] = round(out["invalid_attempts"] / out["attempts"], 3) if attempts else None
    print(json.dumps(out))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--salt", required=True)
    ap.add_argument("--camera", action="store_true", help="every episode with the frame service on (batch 2)")
    ap.add_argument("--no-watchdog", action="store_true", help="never skip S0 entries (batch 2)")
    ap.add_argument("--first", type=int, help="run only the first N entries in sealed order (batch p2)")
    ap.add_argument("--invalidate-unfired", action="store_true", help="log valid attempts whose drawn fault never fired as invalidated")
    a = ap.parse_args()
    if a.first is not None and a.first < 1:
        ap.error("--first must be >= 1")
    manifest = json.loads(Path(a.manifest).read_bytes())  # the runner checks it against the sealed hash
    manifest = {**manifest, "entries": [e for e in manifest["entries"] if e["plant"] in RUNNER_PLANTS]}
    return run_batch(manifest, ROOT / "eval" / "results" / "bench" / a.batch / "progress.jsonl", a)


if __name__ == "__main__":
    raise SystemExit(main())
