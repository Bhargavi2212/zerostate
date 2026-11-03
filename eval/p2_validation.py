"""C12 implementation check: vent F-210 alone to atmosphere through VV-213 in P2's model, at the
x30 step (1.5 process-s), and compare with the exact solution of the same law,
P(t) = Pa cosh(acosh(P0/Pa) - a t), a = R T Cv x / (100 V 3600). Pass = max error < 2 %.

    python eval/p2_validation.py      -> eval/results/p2_validation_<date>.json
                                         plants/p2_gasline/validation/blowdown_overlay.svg
"""

import importlib.util
import json
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("p2_model", ROOT / "plants" / "p2_gasline" / "model.py")
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
P0_KPA, END_KPA, LIMIT_PCT = 2000.0, 102.0, 2.0


def run(dt: float = model.MAX_STEP_PROCESS_S) -> dict:
    m = model.GasLine(seed=0)
    for v in model.VALVES:
        m.pos[v] = 0.0
    m.cmd = {v: 0.0 for v in m.cmd}
    m.pos["VV-213"] = m.cmd["VV-213"] = 100.0  # open from t = 0, as the analytic case assumes
    m.n["F-210"] = P0_KPA * model.VOLUMES["F-210"] / model.RT
    cv, vol = model.VALVES["VV-213"][2], model.VOLUMES["F-210"]
    a = model.RT * cv * 100 / (100 * vol * 3600)
    u0 = math.acosh(P0_KPA / model.PA)
    t_end = (u0 - math.acosh(END_KPA / model.PA)) / a
    rows, worst = [], 0.0
    while m.t < t_end:
        m.step(dt)
        exact = model.PA * math.cosh(max(u0 - a * m.t, 0.0))
        sim = m.p("F-210")
        worst = max(worst, 100 * abs(sim - exact) / exact)
        rows.append((round(m.t, 3), round(sim, 4), round(exact, 4)))
    return {"p0_kpa_abs": P0_KPA, "end_kpa_abs": END_KPA, "cv_vv213": cv, "volume_m3": vol, "step_process_s": dt,
            "vent_process_s": round(t_end, 2), "max_error_pct": round(worst, 4), "limit_pct": LIMIT_PCT,
            "pass": worst < LIMIT_PCT, "rows": rows}


def overlay_svg(rows) -> str:
    w, h, pmax, tmax = 600, 300, P0_KPA, rows[-1][0]

    def line(col, colour):
        pts = " ".join(f"{40 + r[0] / tmax * (w - 60):.1f},{h - 30 - r[col] / pmax * (h - 50):.1f}" for r in rows)
        return f'<polyline fill="none" stroke="{colour}" stroke-width="{3 if col == 2 else 1.5}" points="{pts}"/>'

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="sans-serif" font-size="12">'
            f'{line(2, "#bbb")}{line(1, "#c33")}'
            f'<text x="50" y="20">F-210 blowdown: model (red) vs analytic (grey), 0-{tmax:.0f} process-s, 0-{pmax:.0f} kPa abs</text>'
            "</svg>\n")


def main() -> int:
    r = run()
    commit = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    out = ROOT / "eval" / "results" / f"p2_validation_{datetime.now(UTC):%Y-%m-%d}.json"
    out.write_text(json.dumps({"commit": commit, **{k: v for k, v in r.items() if k != "rows"}}, indent=1) + "\n",
                   encoding="utf-8")
    (ROOT / "plants" / "p2_gasline" / "validation").mkdir(exist_ok=True)
    (ROOT / "plants" / "p2_gasline" / "validation" / "blowdown_overlay.svg").write_text(overlay_svg(r["rows"]), encoding="utf-8")
    print(json.dumps({k: v for k, v in r.items() if k != "rows"}))
    return 0 if r["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
