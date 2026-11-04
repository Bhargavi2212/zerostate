"""Muse Spark alone baseline, pinned before its first live call (plan G23): the prompt in
muse_alone_v1.md, the plan and the whole measured series from the episode bundle (what ZeroState
read, including the hold), one call per episode at temperature 0, the answer mapping in ANSWER. Every call goes through
zerostate.llm.client (proxy, credit ledger, budget stop). A reply that never validates is "unavailable"
and listed, never counted as a pass or a block. Scored by eval/score.py with the same hazard code.

    python eval/baselines/muse_alone.py p1 --dry-run     # projected calls and cost, no call made
    python eval/baselines/muse_alone.py p1               # live: needs MODEL_API_KEY, ZS_PROXY, ZS_CREDITS

Writes eval/results/muse_alone_<batch>.json after every episode (resumable).
"""

import argparse
import importlib.util
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from zerostate.llm import client

ROOT = Path(__file__).parents[2]
HERE = Path(__file__).parent
PROMPT_ID = "muse_alone_v1"
ANSWER = {"pass": "pass", "block": "block"}  # pinned: the model's decision -> the baseline's answer
MAX_POINTS = 120  # per tag, evenly strided over the whole recorded series
REPLY_TOKENS = 100  # cost estimate only


class Decision(BaseModel):
    decision: Literal["pass", "block"]
    reason: str


def _bundle():
    spec = importlib.util.spec_from_file_location("export_bundle", ROOT / "eval" / "tools" / "export_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


export_bundle = _bundle()


def series(signals: dict, t0: float) -> str:
    idx = list(range(len(signals["t"])))
    idx = idx[:: max(1, math.ceil(len(idx) / MAX_POINTS))]
    tags = sorted(k for k in signals if k != "t")
    rows = ["t_s," + ",".join(tags)]
    for i in idx:
        vals = [signals[k][i] for k in tags]
        rows.append(f"{signals['t'][i] - t0:.0f}," + ",".join("" if v is None else f"{v:.4g}" for v in vals))
    return "\n".join(rows)


def messages(run: Path) -> tuple[list[dict], float | None]:
    """The prompt, plan and series; and the decision time = the last reading given (scored from there)."""
    b = export_bundle.build(Path(run))
    t_end = b.signals["t"][-1] if b.signals["t"] else None
    t0 = b.signals["t"][0] if b.signals["t"] else 0.0
    plan = {"points": b.plan.get("points"), "hold_test": b.plan.get("hold_test"),
            "p_depressurised_kpa_abs": b.plan.get("p_depressurised_kpa_abs"),
            "steps": [{"k": s.k, "kind": s.kind, "targets": s.targets, "required_state": s.required_state,
                       "marked_at_t_s": None if s.marked_t is None else round(s.marked_t - t0)} for s in b.steps]}
    text = ((HERE / f"{PROMPT_ID}.md").read_text(encoding="utf-8")
            + "\n\nPLAN:\n" + json.dumps(plan)
            + "\n\nMEASURED SERIES (t_s = seconds from the first reading; empty = no reading):\n"
            + series(b.signals, t0))
    return [{"role": "user", "content": text}], t_end


def run_one(run: Path, call=client.spark_json) -> dict:
    msgs, t = messages(run)
    try:
        d = call(msgs, Decision, "baseline_muse_alone", temperature=0)
    except client.ModelUnavailable as e:
        return {"answer": "unavailable", "t": t, "reason": str(e)}
    return {"answer": ANSWER[d.decision], "t": t, "reason": d.reason}


def episodes(results_dir: Path) -> list[Path]:
    """Episodes the runner recorded as valid (score.py decides which ones count)."""
    return sorted(p for p in results_dir.iterdir() if (p / "verdict.json").exists() and (p / "audit_export.json").exists()
                  and json.loads((p / "verdict.json").read_text(encoding="utf-8")).get("valid"))


def projection(runs: list[Path]) -> dict:
    tin = sum(len(messages(r)[0][0]["content"]) // 4 for r in runs)  # ~4 characters per token
    usd = tin / 1e6 * client.PRICE["spark_in_per_m"] + len(runs) * REPLY_TOKENS / 1e6 * client.PRICE["spark_out_per_m"]
    return {"calls": len(runs), "input_tokens_est": tin, "usd_est": round(usd, 4), "usd_worst_case_with_retries": round(2 * usd, 4)}


def run_batch(runs: list[Path], out: Path, prompt_id: str = PROMPT_ID, call=client.spark_json) -> dict:
    res = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"prompt_id": prompt_id, "model": client.SPARK, "episodes": {}}
    for r in runs:
        if res["episodes"].get(r.name, {}).get("answer") in ANSWER.values():
            continue
        res["episodes"][r.name] = run_one(r, call)
        out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--results-dir", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="print the projected call count and cost; call nothing")
    a = ap.parse_args()
    runs = episodes(a.results_dir or ROOT / "eval" / "results" / "bench" / a.batch)
    if a.dry_run:
        print(json.dumps(projection(runs)))
        return 0
    res = run_batch(runs, ROOT / "eval" / "results" / f"muse_alone_{a.batch}.json")
    print({k: sum(1 for e in res["episodes"].values() if e["answer"] == k) for k in ("pass", "block", "unavailable")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
