"""Run a sealed batch: every manifest entry, in sealed order, through eval/runner.py. Run it from the
worktree checked out at the batch tag (the runner refuses scoring seeds anywhere else).

    python eval/run_benchmark.py --batch p1 --manifest D:/grfics/sealed/manifest_p1.json --salt D:/grfics/sealed/salt_p1

Resumable: an entry with a valid result, or with two INVALID attempts, is not run again. An INVALID
episode is retried once with the same seed; the INVALID rate is reported. Three INVALIDs in a row stop
the batch (a lab fault, e.g. router rules wiped by a Docker restart): fix it, then run the same command.
Watchdog: from 05:00, if the batch would finish after 09:00, S0 entries beyond 10 valid are skipped.
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
STOP_AFTER_INVALID_IN_A_ROW = 3
WATCHDOG_FROM_HOUR, WATCHDOG_FINISH_BY_HOUR, WATCHDOG_KEEP_S0 = 5, 9, 10


def key(e: dict) -> tuple:
    return e["plant"], e["scenario"], e["seed"]


def read_progress(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def done(entry: dict, progress: list[dict]) -> bool:
    tries = [p for p in progress if key(p) == key(entry) and p.get("kind") == "attempt"]
    skipped = any(key(p) == key(entry) and p.get("kind") == "skipped" for p in progress)
    return skipped or any(t["valid"] for t in tries) or len(tries) >= MAX_ATTEMPTS


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
                    "--manifest", a.manifest, "--salt", a.salt], check=False, cwd=ROOT)
    new = sorted(set((ROOT / "runs").glob(f"{entry['scenario']}_seed{entry['seed']}_*")) - before)
    if not new or not (new[-1] / "verdict.json").exists():
        return None
    return {"episode": new[-1].name, **json.loads((new[-1] / "verdict.json").read_text(encoding="utf-8"))}


def run_batch(manifest: dict, progress_p: Path, a, run=run_episode, clock=datetime.now) -> int:
    progress_p.parent.mkdir(parents=True, exist_ok=True)

    def log(rec):
        with open(progress_p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": clock().isoformat(), **rec}) + "\n")

    entries, in_a_row = manifest["entries"], 0
    for i, e in enumerate(entries):
        progress = read_progress(progress_p)
        if done(e, progress):
            continue
        attempts = [p for p in progress if p.get("kind") == "attempt"]
        durations = [p["wall_s"] for p in attempts if "wall_s" in p]
        mean = sum(durations) / len(durations) if durations else None
        s0_valid = sum(1 for p in attempts if p["scenario"] == "S0" and p["valid"])
        remaining = sum(1 for x in entries[i:] if not done(x, progress))
        if watchdog_skip(e, clock(), remaining, mean, s0_valid):
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
    summary(manifest, read_progress(progress_p))
    return 0


def summary(manifest: dict, progress: list[dict]) -> dict:
    attempts = [p for p in progress if p.get("kind") == "attempt"]
    entries = manifest["entries"]
    valid = sum(1 for e in entries if any(key(p) == key(e) and p["valid"] for p in attempts))
    skipped = sum(1 for e in entries if any(key(p) == key(e) and p.get("kind") == "skipped" for p in progress))
    out = {"entries": len(entries), "valid": valid, "invalid": len(entries) - valid - skipped, "skipped": skipped,
           "attempts": len(attempts), "invalid_attempts": sum(1 for p in attempts if not p["valid"])}
    out["invalid_rate"] = round(out["invalid_attempts"] / out["attempts"], 3) if attempts else None
    print(json.dumps(out))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--salt", required=True)
    a = ap.parse_args()
    manifest = json.loads(Path(a.manifest).read_bytes())  # the runner checks it against the sealed hash
    return run_batch(manifest, ROOT / "eval" / "results" / "bench" / a.batch / "progress.jsonl", a)


if __name__ == "__main__":
    raise SystemExit(main())
