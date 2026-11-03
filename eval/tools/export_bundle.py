"""Episode -> bundle.json.gz for the public replay viewer (docs/BUNDLE.md). The viewer reads only this.

    python eval/tools/export_bundle.py eval/results/episodes/S0_seed31_* [--map plants/p1_grfics/plant_map.yaml] [--out DIR]

Input: a published episode folder (audit_export.json, verdict.json, meta.json; truth.jsonl.gz and
events.jsonl when present; runs/<episode>/signals.jsonl when present, else the evaluation windows).
"""

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).parents[2]
BUNDLE_VERSION = "1"
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


def _signals(run: Path, evaluations: list[dict]) -> dict:
    raw = _jsonl(ROOT / "runs" / run.name / "signals.jsonl")
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


def build(run: Path, plant_map: dict | None = None) -> Bundle:
    events = json.loads((run / "audit_export.json").read_text(encoding="utf-8"))
    verdict = json.loads((run / "verdict.json").read_text(encoding="utf-8"))
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    start = next(e for e in events if e["kind"] == "session_start")["payload"]
    plan = start["plan"]
    evals = [e for e in events if e["kind"] == "evaluation"]
    marks = {e["payload"]["k"]: _ts(e["ts"]) for e in events if e["kind"] == "step_done"}
    results = {}
    for e in evals:
        if e["payload"]["source"] == "step":
            st = {f["status"] for f in e["payload"]["findings"]}
            results[e["payload"]["step"]] = "FAIL" if "FAIL" in st else "UNKNOWN" if ("UNKNOWN" in st or not st) else "PASS"
    if verdict.get("verdict") == "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF":
        results.update({s["k"]: "PASS" for s in plan["steps"] if s["kind"] == "final"})
    steps = [Step(k=s["k"], kind=s["kind"], targets=s.get("targets") or ([s["target"]] if s.get("target") else []),
                  required_state=s.get("required_state"), marked_t=marks.get(s["k"]), result=results.get(s["k"]))
             for s in plan["steps"]]
    truth_rows = _jsonl(run / "truth.jsonl.gz", gzip.open)
    truth = None
    if truth_rows:
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
                                rules=e["payload"].get("rules", []), findings=e["payload"]["findings"],
                                verdict_after=e["payload"].get("verdict_after"), window=e["payload"].get("window"))
                     for e in evals],
        verdicts=[VerdictChange(t=_ts(e["ts"]), verdict=e["payload"]["verdict"], source=e["payload"].get("source"),
                                track=e["payload"].get("track", "data_only"), reasons=e["payload"].get("reasons", []))
                  for e in events if e["kind"] == "verdict"],
        signals=_signals(run, evals),
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
    a = ap.parse_args()
    import yaml
    pm = yaml.safe_load(Path(a.map).read_text(encoding="utf-8")) if a.map else None
    for r in a.runs:
        run = Path(r)
        p = write(build(run, pm), Path(a.out) / run.name if a.out else run)
        print(f"{p}  {p.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
