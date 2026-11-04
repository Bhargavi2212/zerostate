"""Episode -> bundle.json.gz for the public replay viewer (docs/BUNDLE.md). The viewer reads only this.

    python eval/tools/export_bundle.py eval/results/episodes/S0_seed31_* [--map plants/p1_grfics/plant_map.yaml] [--out DIR]
                                       [--runs-dir D:/grfics/zs-bench/runs]

Input: a published episode folder (audit_export.json, verdict.json, meta.json; truth.jsonl.gz and
events.jsonl when present; <runs-dir>/<episode>/signals.jsonl when present (default: runs/ in this repo;
read only), else the evaluation windows). signals_sha256 comes from meta.json, else the batch's
signals_sha256.json next to the episode, else the full signals.jsonl; a local file that does not match
the recorded hash is refused.
"""

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).parents[2]
BUNDLE_VERSION = "2"  # "1" still loads: every v2 field defaults to None
KEYLIKE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|Bearer\s+\S+|MODEL_API_KEY\s*[=:]\s*\S+)")
TRUTH_KEYS = ("pressure", "liquid_level", "f1_flow", "f2_flow", "purge_flow", "product_flow")


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    k: int
    kind: str
    targets: list[str]
    required_state: float | None
    marked_t: float | None
    result: str | None  # PASS | FAIL | UNKNOWN | None (not reached)
    marked_by: str | None = None  # v2
    verified_by: str | None = None
    verified_t: float | None = None
    reopened: list[dict] | None = None  # [{by, t, reason}]


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    t: float
    source: str  # step | monitor | plan | process | camera
    step: int | None
    rules: list[str]
    findings: list[dict]
    verdict_after: str | None
    window: dict | None  # the exact evidence the rules saw (as logged; replayable)
    point: str | None = None  # v2: camera evaluations name the display point


class VerdictChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t: float
    verdict: str
    source: str | None
    track: str  # data_only | with_camera
    reasons: list[str]


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle_version: str
    episode: str
    plant: str
    scenario: str | None
    title: str | None
    seed: int | None
    batch: str | None
    expected: list[str]
    result: dict  # verdict, match, valid, problems
    plan_hash: str
    plan: dict
    plant_map: dict | None
    process_time_scale: float
    steps: list[Step]
    evaluations: list[Evaluation]
    verdicts: list[VerdictChange]
    signals: dict  # {"t": [...], tag: [...]} at <= 1 Hz, wall seconds
    camera: list[dict]  # readings with frame hashes, never frames
    truth: dict | None  # eval only: {"eval_only": true, "t": [...], key: [...]} at <= 1 Hz
    faults: list[dict]
    audit: dict  # {"events": n, "chain_head": hash}
    confirmation: dict | None = None  # v2
    assumptions: list[str] | None = None
    plan_check_override: str | None = None
    signals_sha256: str | None = None


def _ts(iso: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(iso).timestamp()


def _jsonl(p: Path, opener=open) -> list[dict]:
    if not p.exists():
        return []
    with opener(p, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _downsample(rows: list[tuple[float, dict]], keys) -> dict:
    out, last = {"t": [], **{k: [] for k in keys}}, None
    for t, vals in rows:
        if last is not None and t - last < 1.0:
            continue
        last = t
        out["t"].append(round(t, 2))
        for k in keys:
            out[k].append(vals.get(k))
    return out


def _signals_sha256(run: Path, meta: dict, full: Path) -> str | None:
    batch = run.parent / "signals_sha256.json"
    recorded = meta.get("signals_sha256") or (json.loads(batch.read_text(encoding="utf-8")).get(run.name) if batch.exists() else None)
    if not full.exists():
        return recorded
    h = hashlib.sha256()
    with open(full, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    if recorded and recorded != h.hexdigest():
        raise SystemExit(f"{run.name}: {full} does not match its recorded signals_sha256; not exported")
    return h.hexdigest()


def _signals(run: Path, evaluations: list[dict], runs_dir: Path) -> dict:
    raw = _jsonl(runs_dir / run.name / "signals.jsonl")
    if raw:
        keys = sorted(k for k in raw[0] if k != "t")
        return _downsample([(r["t"], {k: r[k][0] for k in keys}) for r in raw], keys)
    by_t: dict[float, dict] = {}
    for e in evaluations:  # fall back to what the rules saw
        for tag, samples in ((e["payload"].get("window") or {}).get("samples") or {}).items():
            for s in samples:
                by_t.setdefault(s[0], {})[tag] = s[1]
    keys = sorted({k for v in by_t.values() for k in v})
    return _downsample(sorted(by_t.items()), keys)


def build(run: Path, plant_map: dict | None = None, runs_dir: Path | None = None) -> Bundle:
    runs_dir = Path(runs_dir) if runs_dir else ROOT / "runs"
    events = json.loads((run / "audit_export.json").read_text(encoding="utf-8"))
    verdict = json.loads((run / "verdict.json").read_text(encoding="utf-8"))
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    start = next(e for e in events if e["kind"] == "session_start")["payload"]
    plan = start["plan"]
    evals = [e for e in events if e["kind"] == "evaluation"]
    marks = {e["payload"]["k"]: (_ts(e["ts"]), e["payload"].get("by")) for e in events if e["kind"] == "step_done"}
    verifies = {e["payload"]["k"]: (_ts(e["ts"]), e["payload"].get("by")) for e in events if e["kind"] == "step_verify"}
    reopened: dict[int, list] = {}
    for e in events:
        if e["kind"] == "step_reopen":
            reopened.setdefault(e["payload"]["k"], []).append({"by": e["payload"].get("by"), "t": _ts(e["ts"]),
                                                               "reason": e["payload"].get("reason")})
    results = {}
    for e in evals:
        if e["payload"]["source"] == "step":
            st = {f["status"] for f in e["payload"]["findings"]}
            results[e["payload"]["step"]] = "FAIL" if "FAIL" in st else "UNKNOWN" if ("UNKNOWN" in st or not st) else "PASS"
        elif e["payload"]["source"] == "process" and any(f["status"] == "FAIL" for f in e["payload"]["findings"]):
            results[e["payload"]["step"]] = "FAIL"  # e.g. a step marked out of order
    if verdict.get("verdict") == "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF":
        results.update({s["k"]: "PASS" for s in plan["steps"] if s["kind"] == "final"})
    steps = [Step(k=s["k"], kind=s["kind"], targets=s.get("targets") or ([s["target"]] if s.get("target") else []),
                  required_state=s.get("required_state"), marked_t=marks.get(s["k"], (None, None))[0],
                  result=results.get(s["k"]), marked_by=marks.get(s["k"], (None, None))[1],
                  verified_t=verifies.get(s["k"], (None, None))[0], verified_by=verifies.get(s["k"], (None, None))[1],
                  reopened=reopened.get(s["k"], []))
             for s in plan["steps"]]
    truth_rows = _jsonl(run / "truth.jsonl.gz", gzip.open)
    truth = None
    if truth_rows and "outputs" in truth_rows[0]:  # P1 shape; P2 truth is per unit, not exported
        keys = [k for k in TRUTH_KEYS if k in truth_rows[0].get("outputs", {})]
        truth = {"eval_only": True, **_downsample([(r["t"], r["outputs"]) for r in truth_rows], keys)}
    sc = meta.get("scenario") or {}
    return Bundle(
        bundle_version=BUNDLE_VERSION, episode=run.name, plant=plan["plant"], scenario=sc.get("id"), title=sc.get("title"),
        seed=meta.get("seed"), batch=meta.get("batch"), expected=sc.get("expected", verdict.get("expected", [])),
        result={k: verdict.get(k) for k in ("verdict", "match", "valid", "problems")},
        plan_hash=start["plan_hash"], plan=plan, plant_map=plant_map,
        process_time_scale=start.get("process_time_scale", meta.get("process_time_scale", 1)),
        steps=steps,
        evaluations=[Evaluation(id=e["id"], t=_ts(e["ts"]), source=e["payload"]["source"], step=e["payload"].get("step"),
                                rules=e["payload"].get("rules", []),
                                findings=[{**f, "id": f"{e['id']}:{f['rule_id']}"} for f in e["payload"]["findings"]],
                                verdict_after=e["payload"].get("verdict_after"), window=e["payload"].get("window"),
                                point=e["payload"].get("point"))
                     for e in evals],
        verdicts=[VerdictChange(t=_ts(e["ts"]), verdict=e["payload"]["verdict"], source=e["payload"].get("source"),
                                track=e["payload"].get("track", "data_only"), reasons=e["payload"].get("reasons", []))
                  for e in events if e["kind"] == "verdict"],
        signals=_signals(run, evals, runs_dir),
        signals_sha256=_signals_sha256(run, meta, runs_dir / run.name / "signals.jsonl"),
        confirmation=start.get("confirmation"),
        assumptions=[a["text"] for a in plan.get("assumptions", [])],
        plan_check_override=start.get("plan_check_override"),
        camera=[e["payload"] for e in events if e["kind"] == "camera_reading"],
        truth=truth,
        faults=[e["data"] for e in _jsonl(run / "events.jsonl") if e.get("kind") == "fault"],
        audit={"events": len(events), "chain_head": events[-1]["hash"] if events else None},
    )


def write(bundle: Bundle, out_dir: Path) -> Path:
    text = bundle.model_dump_json()
    if KEYLIKE.search(text):
        raise SystemExit(f"{bundle.episode}: key-like string in the bundle; not written")
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "bundle.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        fh.write(text)
    return p


def load(p: Path) -> Bundle:
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return Bundle.model_validate_json(fh.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--map", help="plant_map.yaml to include for the plant view")
    ap.add_argument("--out", help="output root (default: next to each episode)")
    ap.add_argument("--runs-dir", help="where the full signals.jsonl files are (read only; default: runs/ in this repo)")
    a = ap.parse_args()
    import yaml
    pm = yaml.safe_load(Path(a.map).read_text(encoding="utf-8")) if a.map else None
    for r in a.runs:
        run = Path(r)
        p = write(build(run, pm, a.runs_dir), Path(a.out) / run.name if a.out else run)
        print(f"{p}  {p.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
