"""P1-9: build the smoke table from runs/<episode>/ outputs (verdict.json, audit_export.json,
truth.jsonl, events.jsonl). Writes eval/results/smoke_p1_<date>.md.

    python eval/tools/smoke_table.py runs/S0_seed7_* runs/S1_seed3_* ...
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]


def ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def row(run: Path, basis: str = "") -> dict:
    v = json.loads((run / "verdict.json").read_text(encoding="utf-8"))
    pub = ROOT / "eval" / "results" / "episodes" / run.name
    status = "INVALID" if (pub / "INVALID.md").exists() else "SUPERSEDED" if (pub / "SUPERSEDED.md").exists() else "counted"
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    scale = meta["process_time_scale"]
    events = json.loads((run / "audit_export.json").read_text(encoding="utf-8")) if (run / "audit_export.json").exists() else []
    truth = jsonl(run / "truth.jsonl")
    marks = {e["payload"]["k"]: ts(e["ts"]) for e in events if e["kind"] == "step_done"}
    start = next((e for e in events if e["kind"] == "session_start"), None)
    kinds = {s["kind"]: s["k"] for s in reversed(start["payload"]["plan"]["steps"])} if start else {}
    vent_k, hold_k = kinds.get("vent_open"), kinds.get("hold")  # from the logged plan, not fixed numbers
    steps = start["payload"]["plan"]["steps"] if start else []
    plan = ("block-in" if any(st.get("targets") for st in steps) else "close-purge" if len(steps) == 9
            else "original" if steps else "")
    first = next((e for e in events if e["kind"] == "evaluation"
                  and e["payload"]["verdict_after"] in ("BLOCKED", "ESCALATED")), None)
    first_fail = " + ".join(f"{f['rule_id']} {f['status']}" for f in first["payload"]["findings"]
                            if f["status"] != "PASS") if first else ""
    terminal = next((ts(e["ts"]) for e in events if e["kind"] == "verdict" and e["payload"]["verdict"] in ("BLOCKED", "ESCALATED")), None)
    fault_t = next((e["data"].get("t_vm") for e in jsonl(run / "events.jsonl") if e["kind"] == "fault"), None)
    since = fault_t or marks.get(1)
    to_block = round((terminal - since) * scale) if terminal and since else ""
    vent, vent_start = "", ""
    if vent_k in marks:
        vent_start = round(min(truth, key=lambda r: abs(r["t"] - marks[vent_k]))["outputs"]["pressure"])
        hit = next((r["t"] for r in truth if r["t"] >= marks[vent_k] and r["outputs"]["pressure"] <= 105), None)
        vent = round((hit - marks[vent_k]) * scale) if hit else "not reached"
    hold = ""
    if hold_k in marks:
        p = [r["outputs"]["pressure"] for r in truth if r["t"] >= marks[hold_k]]
        hold = round(min(p), 1) if p else ""
    return {"scenario": v.get("scenario"), "seed": v.get("seed"), "status": status, "plan": plan, "rules_basis": basis, "expected": "/".join(v.get("expected", [])),
            "actual": v.get("verdict") or "invalid", "match": v.get("match", False), "valid": v.get("valid", False),
            "first_block": first_fail, "to_block_process_s": to_block, "vent_start_kpa": vent_start,
            "vent_to_105_process_s": vent,
            "min_hold_kpa": hold, "problems": "; ".join(v.get("problems", []))}


def main(runs: list[str]) -> int:
    # each arg: runs/<episode>[=basis], e.g. runs/S1_seed11_...=replayed under v2
    rows = [row(Path(r.split("=")[0]), r.split("=")[1] if "=" in r else "") for r in runs]
    cols = list(rows[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    out = ROOT / "eval" / "results" / f"smoke_p1_{datetime.now(UTC):%Y-%m-%d}.md"
    out.write_text("# P1 smoke run (tuning seeds)\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    counted = [r for r in rows if r["status"] == "counted"]
    print(f"counted {len(counted)}, all match and valid: {all(r['match'] and r['valid'] for r in counted)}")
    return 0 if all(r["match"] and r["valid"] for r in counted) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
