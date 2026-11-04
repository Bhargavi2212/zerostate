"""Score a sealed batch from its committed episode folders (eval/results/bench/<batch>/), under the two
hazard definitions fixed in docs/DECISIONS.md (Nov 3) before the seal was opened.

    python eval/score.py p1 --manifest D:/grfics/sealed/manifest_p1.json --salt D:/grfics/sealed/salt_p1

Refuses unless sha256(salt + manifest) equals eval/sealed_hash_<batch>.txt. Every episode is checked
(seed in the manifest, batch, plan hash, audit hash chain, replay gives the logged verdicts); a failing
episode is listed and its manifest entry counts as INVALID. Writes eval/results/score_<batch>.{json,md}.
"""

import argparse
import gzip
import importlib.util
import json
import math
import re
import statistics
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

from zerostate.audit.log import AuditLog, canonical, row_hash
from zerostate.audit.replay import replay
from zerostate.config import load_thresholds

ROOT = Path(__file__).parents[1]
NO_DISC = "NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF"
ENGINE = {"p1": "live checks only (Phase 1 engine)", "2": "full engine (live + process + camera)", "p2": "gas line, full engine"}
DEFINITIONS = {"primary": 0.01, "secondary": 0.001}  # flow limit as a fraction of the line's full scale
P1_FULL_SCALE = {"f1": 1000, "f2": 500, "purge": 2000, "product": 500}  # pinned in DECISIONS Nov 3
# P2 (DECISIONS Nov 4, pinned after batch p2 ran, from the model only): flow INTO F-210 through the two lines
# that feed it, each fully open at its design pressure difference = normal operation, S-200 2000 -> XV-201 ->
# C-202 -> XV-203 -> F-210 -> XV-204 -> D-220 1500 kPa, Cv 0.1 each: F = 0.1 * sqrt((2000^2 - 1500^2) / 3).
P2_FULL_SCALE = {"XV-203": 76.3763, "XV-204": 76.3763}
P2_SENSITIVITY = {"pinned (1 %)": 0.01, "x0.5 (0.5 %)": 0.005, "x2 (2 %)": 0.02, "secondary (0.1 %)": 0.001}
PRESSURE_LIMIT_KPA = 150.0
STATE_TOL_PCT = 1.0  # true valve position more than 1 % of travel from the step's required state
LEAK_BINS = ((0.3, 0.6), (0.6, 0.9), (0.9, 1.2), (1.2, 1.5))
Z95 = 1.959964


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seal = _load("seal", ROOT / "eval" / "seal.py")


# ---------------------------------------------------------------- numbers
def wilson(k: int, n: int) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p, z2 = k / n, Z95 * Z95
    mid = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return round(max(0.0, mid - half), 4), round(min(1.0, mid + half), 4)


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "ci_low": lo, "ci_high": hi, "ci_high_pct": None if hi is None else round(hi * 100)}


def show(r: dict) -> str:
    if r["n"] == 0:
        return "0/0"
    if r["k"] == 0:
        return f"0/{r['n']} (upper bound ≈ 3/n = {3 / r['n']:.2f}; Wilson 95 % CI 0–{r['ci_high']:.2f})"
    return f"{r['k']}/{r['n']} (Wilson 95 % CI {r['ci_low']:.2f}–{r['ci_high']:.2f})"


def p2_design_flow() -> float:
    """The P2 pin recomputed from plants/p2_gasline/model.py: normal-operation flow, all blocks open."""
    model = _load("p2_model", ROOT / "plants" / "p2_gasline" / "model.py")
    return round(model.GasLine(seed=0).flows()["XV-203"], 4)


def full_scale(plant: str) -> dict:
    """Flow reference per line: scale_max of each *_flow tag in the committed map (P1), or the line's flow fully
    open at its design pressure difference from the model (P2), checked against the pins."""
    if plant == "p2_gasline":
        if {v: p2_design_flow() for v in P2_FULL_SCALE} != P2_FULL_SCALE:
            raise SystemExit(f"P2 model design flow {p2_design_flow()} differs from the pinned {P2_FULL_SCALE}")
        return dict(P2_FULL_SCALE)
    if plant != "p1_grfics":
        raise SystemExit(f"no flow reference pinned for {plant}")
    tags = yaml.safe_load((ROOT / "plants" / plant / "modbus_map.yaml").read_text(encoding="utf-8"))["tags"]
    fs = {t["tag"].removesuffix("_flow"): t["scale_max"] for t in tags if t["tag"].endswith("_flow")}
    if fs != P1_FULL_SCALE:
        raise SystemExit(f"modbus_map full scales {fs} differ from the pinned {P1_FULL_SCALE}")
    return fs


# ---------------------------------------------------------------- episodes
def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def _jsonl(p: Path, opener=open) -> list[dict]:
    if not p.exists():
        return []
    with opener(p, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def targets(step: dict) -> list[str]:
    return step.get("targets") or ([step["target"]] if step.get("target") else [])


def load_episode(d: Path) -> dict:
    audit = json.loads((d / "audit_export.json").read_text(encoding="utf-8"))
    start = next(e for e in audit if e["kind"] == "session_start")["payload"]
    marks = {}
    for e in audit:
        if e["kind"] == "step_done":
            marks[e["payload"]["k"]] = _ts(e["ts"])  # a re-marked (reopened) step counts from its last mark
    track = {"data_only": [], "with_camera": []}
    for e in audit:
        if e["kind"] == "verdict":
            track[e["payload"].get("track", "data_only")].append((_ts(e["ts"]), e["payload"]["verdict"]))
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    fault_ts = [e["data"].get("t_vm") or e["t"] for e in _jsonl(d / "events.jsonl") if e.get("kind") == "fault"]
    return {"name": d.name, "dir": d, "meta": meta, "audit": audit, "plan": start["plan"], "plan_hash": start["plan_hash"],
            "verdict": json.loads((d / "verdict.json").read_text(encoding="utf-8")), "marks": marks, "track": track,
            "truth": _jsonl(d / "truth.jsonl.gz", gzip.open), "fault_t": min(fault_ts) if fault_ts else None,
            "scale": float(meta.get("process_time_scale") or start.get("process_time_scale") or 1)}


def verdict_time(ep: dict) -> float | None:
    """When the final data-only verdict was reached (its last logged verdict event)."""
    hits = [t for t, v in ep["track"]["data_only"] if v == ep["verdict"].get("verdict")]
    return hits[-1] if hits else None


def faulty(ep: dict) -> bool:
    """A fault actually present: a logged fault event, or an operator variant (the operator does it, no event).
    A scenario fault that never fired (the session ended before its time) leaves the plant clean."""
    sc = ep["meta"].get("scenario") or {}
    return ep["fault_t"] is not None or bool(sc.get("operator"))


def drawn_leak(ep: dict) -> float | None:
    for f in ep["meta"].get("faults") or []:
        for k, v in (f.get("set") or {}).items():
            if k.endswith("leak_pct"):  # P1 f1_leak_pct, P2 XV-204.leak_pct
                return float(v)
    return None


def chain_problem(audit: list[dict]) -> str | None:
    """Each exported row must hash to itself; consecutive rows must link (the chain is global, so a gap in
    ids is another session's rows)."""
    prev = None
    for e in audit:
        if row_hash(e["ts"], e["session"], e["kind"], canonical(e["payload"]), e["prev_hash"]) != e["hash"]:
            return f"audit row {e['id']} does not match its hash"
        if prev and e["id"] == prev["id"] + 1 and e["prev_hash"] != prev["hash"]:
            return f"audit row {e['id']} does not link to row {prev['id']}"
        prev = e
    return None


def replay_problems(ep: dict) -> list[str]:
    params = load_thresholds(ROOT / "plants" / ep["plan"]["plant"] / "thresholds.yaml")
    with tempfile.TemporaryDirectory() as tmp:
        log = AuditLog(Path(tmp) / "audit.sqlite")
        try:
            for e in ep["audit"]:
                log.append(e["session"], e["kind"], e["payload"], ts=e["ts"])
            return replay(log, ep["audit"][0]["session"], params)
        finally:
            log.close()


def episode_problems(ep: dict, batch: str, entries: set) -> list[str]:
    meta, v, out = ep["meta"], ep["verdict"], []
    key = (ep["plan"]["plant"].split("_")[0], (meta.get("scenario") or {}).get("id"), meta.get("seed"))
    if key not in entries:
        out.append(f"{key[1]} seed {key[2]} is not in the sealed {batch} manifest")
    if meta.get("batch") != batch:
        out.append(f"meta batch {meta.get('batch')!r} is not {batch!r}")
    if not v.get("valid"):
        out.append(f"runner: INVALID {v.get('problems')}")
    if not (meta.get("plan_hash") == ep["plan_hash"] == (v.get("stamp") or {}).get("plan_hash", ep["plan_hash"])):
        out.append("plan hash differs between meta.json, the logged session and the verdict stamp")
    if p := chain_problem(ep["audit"]):
        out.append(p)
    data_only = ep["track"]["data_only"]
    if v.get("verdict") != (data_only[-1][1] if data_only else None):
        out.append(f"verdict.json {v.get('verdict')} is not the last logged verdict")
    out += [f"replay: {m}" for m in replay_problems(ep)]
    return out


# ---------------------------------------------------------------- hazard (DECISIONS Nov 3; P2 Nov 4)
def _p1_truth(r: dict) -> tuple[float, dict, dict]:
    o, st = r["outputs"], r["state"]
    flows = {k.removesuffix("_flow"): v for k, v in o.items() if k.endswith("_flow")}
    return o["pressure"], flows, {k.removesuffix("_valve_pos"): v for k, v in st.items() if k.endswith("_valve_pos")}


def _p2_truth(r: dict) -> tuple[float, dict, dict]:
    """F-210 pressure; flow INTO F-210 (XV-203 a->b is into it, XV-204 a->b is out of it: model.VALVES); positions."""
    f = r["flow_kmol_h"]
    return r["pressure_kpa_abs"]["F-210"], {"XV-203": max(f["XV-203"], 0.0), "XV-204": max(-f["XV-204"], 0.0)}, r["position_pct"]


TRUTH = {"p1_grfics": _p1_truth, "p2_gasline": _p2_truth}


def truth(ep: dict, r: dict) -> tuple[float, dict, dict]:
    return TRUTH[ep["plan"]["plant"]](r)


def windows(ep: dict) -> tuple[dict, float | None]:
    """valve -> (from, required state, until), and pressure's start. A line counts from its own isolate mark, the
    vent valve from the vent_close mark, pressure from the vent_close mark. Flow and position start after
    the step's settle time: the operator acts only after declaring the step, so the valve is still moving
    at the mark itself; the start is the engine's own (the later of the step's settle and the plant's
    min_settle_wall_s; P2: the operator's write lands ~4.5 s wall after the mark). A plan that reopens its vent
    after the vent_close (P2's final vent after the hold, which sits at 200 kPa by design) ends that valve's
    window at the reopening mark, and pressure counts only from the release (NO_DISCREPANCY), when the job
    says the work is down; not evaluated without a release."""
    steps = ep["plan"]["steps"]
    vents = {t for s in steps if s["kind"] in ("vent_open", "vent_close") for t in targets(s)}
    closed = {t for s in steps if s["kind"] == "vent_close" for t in targets(s)}
    reopens = any(s["kind"] == "vent_open" and set(targets(s)) & closed
                  and any(c["kind"] == "vent_close" and c["k"] < s["k"] for c in steps) for s in steps)
    floor_wall = settle_floor_wall_s(ep)
    win, p_from = {}, None
    if reopens:
        p_from = verdict_time(ep) if ep["verdict"].get("verdict") == NO_DISC else None
    for s in steps:
        if s["k"] not in ep["marks"]:
            continue
        if s["kind"] == "vent_open":
            for v in targets(s):
                if v in win:  # reopened after its vent_close
                    win[v] = (*win[v][:2], ep["marks"][s["k"]])
            continue
        if s["kind"] not in ("isolate", "vent_close"):
            continue
        t0 = ep["marks"][s["k"]] + max((s.get("settle_process_s") or 0) / ep["scale"], floor_wall)
        if s["kind"] == "vent_close" and not reopens:
            p_from = ep["marks"][s["k"]]
        for v in targets(s):
            if s["kind"] == "vent_close" or v not in vents:
                win[v] = (t0, float(s["required_state"]), math.inf)
    return win, p_from


def settle_floor_wall_s(ep: dict) -> float:
    """The plant's min_settle_wall_s (thresholds), the floor the engine puts under every step's settle."""
    plant = ep["plan"].get("plant")
    path = ROOT / "plants" / str(plant) / "thresholds.yaml"
    return float(load_thresholds(path).get("min_settle_wall_s", 0)) if plant and path.exists() else 0.0


def skipped(ep: dict) -> list[int]:
    """Plan steps with no mark: before a later marked step, or at all when the session reached NO_DISCREPANCY.
    Steps never reached because the session stopped on a block are not skipped."""
    marked = ep["marks"]
    released = ep["verdict"].get("verdict") == NO_DISC
    return [s["k"] for s in ep["plan"]["steps"] if s["kind"] != "final" and s["k"] not in marked
            and (released or any(m > s["k"] for m in marked))]


def conditions(ep: dict, frac: float, fs: dict, since: float | None = None) -> dict:
    """First time each hazard condition is met (from `since` when given) -> {condition: {t, value}}."""
    win, p_from = windows(ep)
    hits = {}
    for r in ep["truth"]:
        t = r["t"]
        if since is not None and t < since:
            continue
        p, flows, positions = truth(ep, r)
        if p_from is not None and t >= p_from and p > PRESSURE_LIMIT_KPA:
            hits.setdefault("pressure", {"t": t, "value": round(p, 2)})
        for v, (t0, req, until) in win.items():
            if not t0 <= t < until:
                continue
            pos = positions[v]
            if v in fs and flows[v] > frac * fs[v]:
                f = flows[v]
                hits.setdefault(f"flow:{v}", {"t": t, "value": round(f, 3), "pct_full_scale": round(100 * f / fs[v], 3)})
            if abs(pos - req) > STATE_TOL_PCT:
                hits.setdefault(f"state:{v}", {"t": t, "value": round(pos, 2)})
    for k in skipped(ep):
        hits[f"skipped:{k}"] = {"t": None, "value": None}
    return hits


def label(hits: dict, is_faulty: bool) -> str:
    return "unsafe" if hits else "fault, below hazard limits" if is_faulty else "clean"


def severity(ep: dict, since: float, fs: dict) -> dict:
    """Severity at release: max true pressure and max isolated-line flow (% of full scale) after `since`."""
    win, _ = windows(ep)
    rows = [r for r in ep["truth"] if r["t"] >= since]
    flows = [100 * truth(ep, r)[1][v] / fs[v] for r in rows for v, (t0, _, until) in win.items() if v in fs and t0 <= r["t"] < until]
    return {"max_pressure_kpa": round(max((truth(ep, r)[0] for r in rows), default=0), 2) if rows else None,
            "max_isolated_flow_pct": round(max(flows), 3) if flows else None}


def first_finding(ep: dict) -> tuple[str, str] | None:
    """The first FAIL finding in the audit (else the first UNKNOWN), as (rule id, message)."""
    found = [f for e in ep["audit"] if e["kind"] == "evaluation" for f in e["payload"]["findings"]]
    for status in ("FAIL", "UNKNOWN"):
        for f in found:
            if f["status"] == status:
                return f["rule_id"], f["message"]
    return None


def mismatch_note(ep: dict) -> str:
    v = ep["verdict"]
    reasons = (v.get("stamp") or {}).get("reasons") or []
    rule = reasons[0].split(":")[0] if reasons else None
    first = first_finding(ep)
    hold = next((s["k"] for s in ep["plan"]["steps"] if s["kind"] == "hold"), None)
    leak = drawn_leak(ep)
    m = re.search(r"(\w+_flow) = ([-\d.]+)", first[1]) if first else None
    if rule == "LIVE-VALVE" and m and leak is not None and hold not in ep["marks"]:
        return (f"caught by flow before the hold: drawn leak {leak:.3f} %, measured {m[1]} = {m[2]}; "
                f"expected {'/'.join(v.get('expected', []))}, got {v.get('verdict')}")
    return (f"expected {'/'.join(v.get('expected', []))}, got {v.get('verdict')}: deciding rule {rule}; "
            f"first {'FAIL' if first else 'finding'}: {f'{first[0]}: {first[1]}' if first else 'none'}")


def score_episode(ep: dict, fs: dict) -> dict:
    v, vt = ep["verdict"].get("verdict"), verdict_time(ep)
    out = {"episode": ep["name"], "scenario": ep["meta"]["scenario"]["id"], "seed": ep["meta"]["seed"], "verdict": v,
           "match": bool(ep["verdict"].get("match")), "fault": faulty(ep), "leak_pct": drawn_leak(ep),
           "verdict_t": vt, "fault_t": ep["fault_t"], "label": {}, "conditions": {}, "dangerous_miss": {}}
    for name, frac in DEFINITIONS.items():
        hits = conditions(ep, frac, fs)
        out["label"][name], out["conditions"][name] = label(hits, out["fault"]), hits
        out["dangerous_miss"][name] = v == NO_DISC and vt is not None and bool(conditions(ep, frac, fs, since=vt))
    if v == NO_DISC and vt is not None:
        out["severity_at_release"] = severity(ep, vt, fs)
    if v in ("BLOCKED", "ESCALATED") and vt is not None and ep["fault_t"] is not None:
        out["time_to_block_wall_s"] = round(vt - ep["fault_t"], 2)
        out["time_to_block_process_s"] = round((vt - ep["fault_t"]) * ep["scale"], 1)
    out["hold_fail"] = any(f["rule_id"] == "LIVE-HOLD" and f["status"] == "FAIL"
                           for e in ep["audit"] if e["kind"] == "evaluation" for f in e["payload"]["findings"])
    cam = ep["track"]["with_camera"]  # logged only when the camera track's own verdict changes
    if vc := ep["verdict"].get("verdict_with_camera") or (cam[-1][1] if cam else None):
        out["verdict_with_camera"] = vc
        out["camera_own_verdict"] = bool(cam)
    reads = [e["payload"] for e in ep["audit"] if e["kind"] == "camera_reading"]
    if reads or cam:
        out["camera_coverage"] = camera_coverage(reads, ep["verdict"].get("camera_pending"))
    if not out["match"]:
        out["note"] = mismatch_note(ep)
    elif (ep["meta"].get("scenario") or {}).get("faults") and not out["fault"]:
        first = first_finding(ep)
        out["note"] = (f"fault never injected: the session ended ({v}) before the fault's time, so truth labels it clean "
                       f"and a block counts as a false block; first finding: {f'{first[0]}: {first[1]}' if first else 'none'}")
    return out


def score_decisions(decisions: dict, eps: dict, fs: dict) -> dict:
    """A baseline's pass/block per episode, scored with the same hazard code: a pass at time t is a
    dangerous miss when a condition is met from t to the episode end."""
    answered = {n: d for n, d in decisions.items() if n in eps and d.get("answer") in ("pass", "block")}
    out = {"dangerous_miss": {}, "unanswered": sorted(set(eps) - set(answered)), "whole_job_only": {}, "misses_by_scenario": {}}
    whole = [n for n in answered if whole_job(eps[n])]
    for name, frac in DEFINITIONS.items():
        missed = [n for n, d in answered.items() if d["answer"] == "pass" and conditions(eps[n], frac, fs, since=d["t"])]
        out["dangerous_miss"][name] = rate(len(missed), len(answered))
        out["whole_job_only"][name] = rate(sum(n in whole for n in missed), len(whole))
        out["misses_by_scenario"][name] = dict(Counter(eps[n]["meta"]["scenario"]["id"] for n in missed))
    clean = [n for n in answered if label(conditions(eps[n], DEFINITIONS["primary"], fs), faulty(eps[n])) == "clean"]
    out["false_blocks"] = rate(sum(1 for n in clean if answered[n]["answer"] == "block"), len(clean))
    out["passes"] = sum(1 for d in answered.values() if d["answer"] == "pass")
    out["decided_on"] = {"k": len(answered), "n": len(eps), "whole_job": sum(whole_job(eps[n]) for n in answered)}
    return out


def sensitivity(chosen: dict, rows: list[dict], fs: dict) -> dict:
    """P2's flow limit pinned after the batch ran: the same counts at the pin, half, double and the 0.1 % secondary."""
    out = {}
    for name, frac in P2_SENSITIVITY.items():
        miss = sum(r["verdict"] == NO_DISC and r["verdict_t"] is not None and bool(conditions(ep, frac, fs, since=r["verdict_t"]))
                   for ep, r in zip(chosen.values(), rows, strict=True))
        labels = [label(conditions(ep, frac, fs), r["fault"]) for ep, r in zip(chosen.values(), rows, strict=True)]
        clean = [r for r, lab in zip(rows, labels, strict=True) if lab == "clean"]
        out[name] = {"limit_kmol_h": round(frac * fs["XV-203"], 4), "dangerous_miss": rate(miss, len(rows)),
                     "labels": dict(Counter(labels)),
                     "false_blocks": rate(sum(r["verdict"] in ("BLOCKED", "ESCALATED") for r in clean), len(clean))}
    return out


def camera_coverage(reads: list[dict], pending) -> dict:
    """How much of the camera's work produced a reading: next to its accuracy, never instead of it."""
    note = [str(r.get("note") or "") for r in reads]
    return {"readings": len(reads), "readable": sum(bool(r.get("readable")) for r in reads),
            "no_frame": sum(n.startswith("no frame") for n in note),
            "timeouts": sum(n.startswith("no frame") and ("timeout" in n.lower() or "timed out" in n.lower()) for n in note),
            "model_unavailable": sum(n.startswith(("locate unavailable", "read unavailable")) for n in note),
            "located_by_map": sum(r.get("located_by") == "map" for r in reads),
            "pending_at_stop": int(pending or 0)}


def whole_job(ep: dict) -> bool:
    """Every non-final plan step was marked: the episode ran the whole job, not stopped early on a block."""
    return all(s["k"] in ep["marks"] for s in ep["plan"]["steps"] if s["kind"] != "final")


# ---------------------------------------------------------------- batch
def plan_set(path: Path, entries: set) -> dict:
    """Plan-check set results (eval/plan_benchmark.py output) for batches with plan entries."""
    res = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = res["cases"]
    by = {}
    for r in rows:
        b = by.setdefault(r["case"], {"n": 0, "blocked": 0, "label_match": 0})
        b["n"] += 1
        b["blocked"] += bool(r["blocked"])
        b["label_match"] += bool(r["label_match"])
    pc0 = [r for r in rows if r["case"] == "PC0"]
    planted = [r for r in rows if r["case"] != "PC0"]
    return {"n": len(rows), "cases": len(rows), "label_match": sum(bool(r["label_match"]) for r in rows), "per_case": by,
            "errors": {"k": sum(bool(r["blocked"]) for r in planted), "n": len(planted)},
            "false_blocks": rate(sum(bool(r["blocked"]) for r in pc0), len(pc0)),
            "not_in_manifest": [f"{r['case']} seed {r['seed']}" for r in rows if ("plan", r["case"], r["seed"]) not in entries],
            "missing": sorted(f"{c} seed {s}" for p, c, s in entries
                              if p == "plan" and not any((r["case"], r["seed"]) == (c, s) for r in rows))}


def score(batch: str, manifest_p: Path, salt_p: Path, results_dir: Path, hash_p: Path | None = None,
          plan_results: Path | None = None, muse_results: Path | None = None) -> dict:
    manifest, h = seal.load(manifest_p, salt_p)
    hash_p = hash_p or ROOT / "eval" / f"sealed_hash_{batch}.txt"
    committed = hash_p.read_text(encoding="utf-8").strip() if hash_p.exists() else None
    if h != committed:
        raise SystemExit(f"refused: sha256(salt + manifest) {h[:12]} does not match {hash_p.name} ({str(committed)[:12]})")
    if manifest.get("batch") != batch:
        raise SystemExit(f"refused: manifest is batch {manifest.get('batch')!r}, not {batch!r}")
    all_entries = {(e["plant"], e["scenario"], e["seed"]) for e in manifest["entries"]}
    entries = [e for e in manifest["entries"] if e["plant"] != "plan"]
    folders = sorted(p for p in Path(results_dir).iterdir() if (p / "meta.json").exists() and (p / "audit_export.json").exists())
    loaded = {d.name: load_episode(d) for d in folders}
    problems = {n: episode_problems(ep, batch, all_entries) for n, ep in loaded.items()}
    progress = _jsonl(Path(results_dir) / "progress.jsonl")
    inv = {p["episode"]: p["reason"] for p in progress if p.get("kind") == "invalidated"}  # run_benchmark --invalidate-unfired
    for n, found in problems.items():
        if n in inv:
            found.append(f"invalidated: {inv[n]}")

    chosen, invalid = {}, []
    for e in entries:
        cands = [n for n, ep in loaded.items() if ep["meta"]["seed"] == e["seed"] and ep["meta"]["scenario"]["id"] == e["scenario"]]
        good = [n for n in cands if not problems[n]]
        if good:
            chosen[good[-1]] = loaded[good[-1]]
        else:
            invalid.append({**e, "episodes": {n: problems[n] for n in cands} or "no episode folder"})
    listed = {n: p for n, p in problems.items() if p}
    stray = sorted(set(loaded) - set(chosen) - set(listed))
    plant = next(iter(chosen.values()))["plan"]["plant"] if chosen else "p1_grfics"
    fs = full_scale(plant)
    rows = [score_episode(ep, fs) for ep in chosen.values()]

    def count(pred, among):
        return sum(1 for r in among if pred(r))

    clean = [r for r in rows if r["label"]["primary"] == "clean"]
    whole = [r for r, ep in zip(rows, chosen.values(), strict=True) if whole_job(ep)]
    fault_rows = [r for r in rows if r["fault"]]
    per_scenario = {}
    for r in rows:
        s = per_scenario.setdefault(r["scenario"], {"n": 0, "blocked": 0, "escalated": 0, "no_discrepancy": 0, "match": 0, "notes": []})
        s["n"] += 1
        s["blocked"] += r["verdict"] == "BLOCKED"
        s["escalated"] += r["verdict"] == "ESCALATED"
        s["no_discrepancy"] += r["verdict"] == NO_DISC
        s["match"] += r["match"]
        if "note" in r:
            s["notes"].append(f"seed {r['seed']}: {r['note']}")
    bins = {f"{lo}-{hi} %": {"n": 0, "blocked": 0, "escalated": 0, "no_discrepancy": 0, "hold_fail": 0, "episodes": []}
            for lo, hi in LEAK_BINS}
    for r in rows:
        if r["leak_pct"] is None:
            continue
        b = next((f"{lo}-{hi} %" for lo, hi in LEAK_BINS if lo <= r["leak_pct"] < hi or (hi == 1.5 and r["leak_pct"] == hi)), None)
        if b is None:
            continue
        x = bins[b]
        x["n"] += 1
        x["blocked"] += r["verdict"] == "BLOCKED"
        x["escalated"] += r["verdict"] == "ESCALATED"
        x["no_discrepancy"] += r["verdict"] == NO_DISC
        x["hold_fail"] += r["hold_fail"]
        x["episodes"].append(f"{r['scenario']} seed {r['seed']} ({r['leak_pct']:.3f} %)")
    ttb = {}
    for r in rows:
        if "time_to_block_process_s" in r:
            ttb.setdefault(r["scenario"], []).append(r["time_to_block_process_s"])
    cam_rows = [r for r in rows if "verdict_with_camera" in r]
    attempts = [p for p in progress if p.get("kind") == "attempt"]
    ids = [json.loads((Path(results_dir) / n / "ids.json").read_text(encoding="utf-8")) for n in chosen]

    reference = ("P1 scale_max: f1 1000, f2 500, purge 2000, product 500" if plant == "p1_grfics" else
                 f"P2: flow into F-210 through XV-203 and XV-204, reference {P2_FULL_SCALE['XV-203']} kmol/h = each line fully "
                 "open at its design pressure difference (normal operation from the model; pinned Nov 4 after batch p2 ran)")
    out = {
        "batch": batch, "engine": ENGINE.get(batch, batch), "seal_hash": h,
        "plan_hashes": sorted({ep["plan_hash"] for ep in chosen.values()}),
        "definitions": {
            "primary": "true work-segment pressure > 150 kPa abs; true flow through an isolated line > 1 % of its full scale "
                       f"({reference}); a required step skipped; an isolation "
                       "point in the wrong true state (position more than 1 % from the step's required state)",
            "secondary": "the same four conditions with the flow limit at 0.1 % of full scale",
            "dangerous_miss": "NO_DISCREPANCY and a condition met at any time from that verdict to the episode end; n = scored episodes",
            "windows": "a line's flow and state count from its own isolate mark plus the step's settle time, the vent valve's "
                       "from the vent_close mark plus its settle time, pressure from the vent_close mark (not evaluated if never reached)",
            "label": "from truth after the isolation marks, whatever the verdict; descriptive only for BLOCKED or ESCALATED",
            "false_block": "BLOCKED or ESCALATED on an episode labelled clean (as pre-registered in EVAL); the split is reported",
            "decided_on": "a system decided on an episode when it gave a verdict there; it saw the whole job when every "
                          "non-final plan step was marked before its decision (an episode ZeroState blocked early stops "
                          "there, so a baseline never faces the rest of that job)",
        },
        "n_scored": len(rows),
        "dangerous_miss": {d: rate(count(lambda r, d=d: r["dangerous_miss"][d], rows), len(rows)) for d in DEFINITIONS},
        "missed_faults": {"k": count(lambda r: r["verdict"] == NO_DISC and not r["dangerous_miss"]["primary"], fault_rows),
                          "n": len(fault_rows)},
        "missed_faults_secondary": {"k": count(lambda r: r["verdict"] == NO_DISC and not r["dangerous_miss"]["secondary"], fault_rows),
                                    "n": len(fault_rows)},
        "false_blocks": {**rate(count(lambda r: r["verdict"] in ("BLOCKED", "ESCALATED"), clean), len(clean)),
                         "blocked": count(lambda r: r["verdict"] == "BLOCKED", clean),
                         "escalated": count(lambda r: r["verdict"] == "ESCALATED", clean)},
        "decided_on": {"k": len(rows), "n": len(rows), "whole_job": sum(map(whole_job, chosen.values()))},
        "whole_job_only": {d: rate(count(lambda r, d=d: r["dangerous_miss"][d], whole), len(whole)) for d in DEFINITIONS},
        "labels": {d: dict(Counter(r["label"][d] for r in rows)) for d in DEFINITIONS},
        "time_to_block_process_s": {s: {"n": len(v), "median": statistics.median(v), "min": min(v), "max": max(v)} for s, v in sorted(ttb.items())},
        "severity_at_release": {r["episode"]: r["severity_at_release"] for r in rows if "severity_at_release" in r},
        "hold_by_leak_bin": bins,
        "invalid": {"k": len(invalid), "n": len(entries), "attempts": len(attempts),
                    "invalid_attempts": sum(1 for p in attempts if not p.get("valid") or p.get("episode") in inv)},
        "invalid_entries": invalid,
        **({"sensitivity": sensitivity(chosen, rows, fs)} if plant == "p2_gasline" else {}),
        # pinned (G23) on P1's signals; P2's last mark opens the final vent at the 200 kPa hold
        **({"baselines_not_run": "gauge rule: pinned for P1's signals only; Muse Spark alone: not run on P2"}
           if plant != "p1_grfics" else {}),
        # the write witnesses per scored episode: P1's IDS (9100001 ZeroState Modbus writes, 9100002 the operator's),
        # P2's server write log (runner postflight); C1
        **({"p2_writes": {"n": len(ids), "zerostate": sum(i["p2_writes"]["zerostate"] for i in ids),
                          "other": sum(i["p2_writes"]["other"] for i in ids),
                          "operator_missing": sum(i["p2_writes"]["operator_allowed"] == 0 for i in ids)}}
           if ids and "p2_writes" in ids[0] else
           {"ids": {"n": len(ids), "zerostate_writes": sum(i["9100001"] for i in ids),
                    "operator_missing": sum(i["9100002"] == 0 for i in ids)}} if ids else {}),
        "episode_problems": listed,
        "not_scored": stray,
        "per_scenario": dict(sorted(per_scenario.items())),
        "camera": {"with_camera_blocked": count(lambda r: r["verdict_with_camera"] == "BLOCKED", cam_rows),
                   "with_camera_escalated": count(lambda r: r["verdict_with_camera"] == "ESCALATED", cam_rows),
                   "data_only_blocked": count(lambda r: r["verdict"] == "BLOCKED", cam_rows), "n": len(cam_rows),
                   "camera_added_block": count(lambda r: r["verdict_with_camera"] != NO_DISC and r["verdict"] == NO_DISC, cam_rows),
                   "camera_removed_block": count(lambda r: r["verdict_with_camera"] == NO_DISC and r["verdict"] != NO_DISC, cam_rows),
                   "by_scenario": {sc: {"n": len(rs), "with_camera_blocked": count(lambda r: r["verdict_with_camera"] == "BLOCKED", rs),
                                        "data_only_blocked": count(lambda r: r["verdict"] == "BLOCKED", rs),
                                        "camera_own_verdict": count(lambda r: r["camera_own_verdict"], rs)}
                                   for sc in sorted({r["scenario"] for r in cam_rows})
                                   for rs in [[r for r in cam_rows if r["scenario"] == sc]]},
                   "coverage": {k: sum(r["camera_coverage"][k] for r in rows if "camera_coverage" in r)
                                for k in ("readings", "readable", "no_frame", "timeouts", "model_unavailable",
                                          "located_by_map", "pending_at_stop")},
                   "timeouts_per_episode": {r["episode"]: r["camera_coverage"]["timeouts"]
                                            for r in rows if "camera_coverage" in r}},
        "baselines": baselines(chosen, fs, muse_results or ROOT / "eval" / "results" / f"muse_alone_{batch}.json"),
        "episodes": rows,
    }
    if plan_results:
        out["plan_set"] = plan_set(plan_results, all_entries)
    return out


def baselines(eps: dict, fs: dict, muse_results: Path) -> dict:
    out = {}
    gauge_p = ROOT / "eval" / "baselines" / "gauge_rule.py"
    p1 = all(ep["plan"]["plant"] == "p1_grfics" for ep in eps.values())
    if gauge_p.exists() and p1:
        gauge = _load("gauge_rule", gauge_p)
        out["gauge_rule"] = score_decisions({n: gauge.decide(ep["dir"]) for n, ep in eps.items()}, eps, fs)
    if Path(muse_results).exists():
        out["muse_alone"] = score_decisions(json.loads(Path(muse_results).read_text(encoding="utf-8"))["episodes"], eps, fs)
    return out


# ---------------------------------------------------------------- output
def markdown(s: dict) -> str:
    L = [f"# Score: batch {s['batch']}", "", f"- Engine: **{s['engine']}**", f"- Seal hash: `{s['seal_hash']}`",
         f"- Plan hash: {', '.join(f'`{h}`' for h in s['plan_hashes'])}", f"- Scored episodes: {s['n_scored']}", "",
         "## Hazard definitions (DECISIONS Nov 3)", ""]
    L += [f"- **{k}**: {v}" for k, v in s["definitions"].items()]
    L += ["", "## Results", "", "| Measure | Result |", "|---|---|"]
    L += [f"| Dangerous misses, {d} | {show(s['dangerous_miss'][d])} |" for d in DEFINITIONS]
    L += [f"| Missed faults (fault, NO_DISCREPANCY, no condition met), primary | {s['missed_faults']['k']}/{s['missed_faults']['n']} |",
          f"| False blocks on clean episodes (BLOCKED or ESCALATED) | {show(s['false_blocks'])} |",
          f"| — of which BLOCKED / ESCALATED | {s['false_blocks']['blocked']} / {s['false_blocks']['escalated']} |",
          f"| ZeroState decided on | {s['decided_on']['k']} of {s['decided_on']['n']} (whole job in {s['decided_on']['whole_job']}) |",
          f"| INVALID entries | {s['invalid']['k']}/{s['invalid']['n']} (attempts: {s['invalid']['invalid_attempts']} INVALID of {s['invalid']['attempts']}) |"]
    for name, b in s["baselines"].items():
        d_on = b["decided_on"]
        L += [f"| Baseline {name}: decided on | {d_on['k']} of {d_on['n']} (whole job in {d_on['whole_job']}) |"]
        L += [f"| Baseline {name}: dangerous misses, {d} | {show(b['dangerous_miss'][d])} |" for d in DEFINITIONS]
        L += [f"| Baseline {name}: {d} misses by scenario | "
              + (", ".join(f"{sc} {k}" for sc, k in sorted(b["misses_by_scenario"][d].items())) or "none") + " |"
              for d in DEFINITIONS]
        L += [f"| Baseline {name}: false blocks | {show(b['false_blocks'])} |"]
    w = s["whole_job_only"]
    L += ["", f"## Like for like: the {s['decided_on']['whole_job']} episodes where every system saw the whole job", "",
          "In the other episodes ZeroState blocked early, the job stopped there, and a baseline judged only that early state.",
          "", "| System | " + " | ".join(f"Dangerous misses, {d}" for d in DEFINITIONS) + " |",
          "|---|" + "---|" * len(DEFINITIONS)]
    L += ["| ZeroState | " + " | ".join(show(w[d]) for d in DEFINITIONS) + " |"]
    L += [f"| Baseline {name} | " + " | ".join(show(b["whole_job_only"][d]) for d in DEFINITIONS) + " |"
          for name, b in s["baselines"].items()]
    L += ["", "Labels from truth (descriptive for BLOCKED / ESCALATED):", ""]
    L += [f"- {d}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) for d, c in s["labels"].items()]
    L += ["", "## Per scenario", "", "| Scenario | n | BLOCKED | ESCALATED | NO_DISCREPANCY | match | notes |", "|---|---|---|---|---|---|---|"]
    for sc, x in s["per_scenario"].items():
        L.append(f"| {sc} | {x['n']} | {x['blocked']} | {x['escalated']} | {x['no_discrepancy']} | {x['match']}/{x['n']} | {'; '.join(x['notes'])} |")
    L += ["", "## Hold detection by drawn leak size (counts; n ≤ 5 per bin, so no rates)", "",
          "| Leak bin | n | BLOCKED | ESCALATED | NO_DISCREPANCY | LIVE-HOLD FAIL |", "|---|---|---|---|---|---|"]
    L += [f"| {b} | {x['n']} | {x['blocked']} | {x['escalated']} | {x['no_discrepancy']} | {x['hold_fail']} |" for b, x in s["hold_by_leak_bin"].items()]
    L += ["", "## Time to first BLOCKED or ESCALATED (process seconds from the fault event; episodes with a logged fault event only)", "", "| Scenario | n | median | min | max |", "|---|---|---|---|---|"]
    L += [f"| {sc} | {x['n']} | {x['median']} | {x['min']} | {x['max']} |" for sc, x in s["time_to_block_process_s"].items()]
    L += ["", "## Severity at release (truth after NO_DISCREPANCY)", "", "| Episode | max pressure kPa | max isolated-line flow % of full scale |", "|---|---|---|"]
    L += [f"| {e} | {x['max_pressure_kpa']} | {x['max_isolated_flow_pct']} |" for e, x in s["severity_at_release"].items()]
    if s["camera"]["n"]:
        c = s["camera"]
        L += ["", "## Camera vs data-only (idealised camera)", "",
              (f"With-camera track blocked {c['with_camera_blocked']} of {c['n']} (escalated {c['with_camera_escalated']}); data-only blocked {c['data_only_blocked']} of {c['n']}. "
              f"The camera added a block where data-only gave NO_DISCREPANCY in {c['camera_added_block']}; "
              f"with-camera NO_DISCREPANCY where data-only did not: {c['camera_removed_block']}."), "",
              "| Scenario | n | with-camera BLOCKED | data-only BLOCKED | camera track logged its own verdict |", "|---|---|---|---|---|"]
        L += [f"| {sc} | {x['n']} | {x['with_camera_blocked']} | {x['data_only_blocked']} | {x['camera_own_verdict']} |"
              for sc, x in c["by_scenario"].items()]
        v = c["coverage"]
        L += ["", (f"Coverage: {v['readable']} of {v['readings']} camera readings readable; no frame {v['no_frame']} "
                   f"(timeouts {v['timeouts']}), model unavailable {v['model_unavailable']}, located by the calibrated map "
                   f"{v['located_by_map']}, reads still pending at stop {v['pending_at_stop']}."), "",
              "| Episode | camera timeouts |", "|---|---|"]
        L += [f"| {e} | {n} |" for e, n in c["timeouts_per_episode"].items()]
    if "plan_set" in s:
        p = s["plan_set"]
        L += ["", "## Plan set", "", (f"{p['label_match']}/{p['n']} cases match their labels; false blocks on correct plans {show(p['false_blocks'])}. "
              f"Manifest plan entries without a result: {', '.join(p['missing']) or 'none'}; results not in the manifest: "
              f"{', '.join(p['not_in_manifest']) or 'none'}."), "", "| Case | n | blocked | label match |", "|---|---|---|---|"]
        L += [f"| {c} | {x['n']} | {x['blocked']} | {x['label_match']}/{x['n']} |" for c, x in sorted(p["per_case"].items())]
    L += ["", "## INVALID entries and episode problems", ""]
    L += [f"- {e['scenario']} seed {e['seed']}: {e['episodes']}" for e in s["invalid_entries"]] or ["- none"]
    L += [f"- {n}: {'; '.join(p)}" for n, p in s["episode_problems"].items()]
    return "\n".join(L) + "\n"


def never_say(text: str) -> list[str]:
    """The project's single never-say checker (src/zerostate/wording.py)."""
    from zerostate import wording
    return wording.hits(text)


def write(s: dict, out_dir: Path) -> list[Path]:
    j, md = json.dumps(s, indent=1, default=str), markdown(s)
    hits = [never_say(t) for t in (j, md)]
    if any(hits):
        raise SystemExit(f"never-say words in the score output, not written: {hits}")
    s["never_say_check"] = "clean"
    j = json.dumps(s, indent=1, default=str)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"score_{s['batch']}.json", out_dir / f"score_{s['batch']}.md"]
    paths[0].write_text(j, encoding="utf-8")
    paths[1].write_text(md, encoding="utf-8")
    return paths


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--salt", required=True, type=Path)
    ap.add_argument("--results-dir", type=Path, help="episode folders (default eval/results/bench/<batch>)")
    ap.add_argument("--plan-results", type=Path, help="eval/plan_benchmark.py output, for batches with plan entries")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results")
    a = ap.parse_args()
    s = score(a.batch, a.manifest, a.salt, a.results_dir or ROOT / "eval" / "results" / "bench" / a.batch,
              plan_results=a.plan_results)
    for p in write(s, a.out):
        print(p)
    print(f"dangerous misses: primary {show(s['dangerous_miss']['primary'])}; secondary {show(s['dangerous_miss']['secondary'])}")
    print(f"never-say check: {s['never_say_check']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
