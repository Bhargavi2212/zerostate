"""P2 gas line physics (SPEC.md): isothermal nitrogen volumes joined by valves, pure and seedable.

Flow through a valve at opening x %: F = Cv * x/100 * sqrt(max(P_up^2 - P_dn^2, 0)) kmol/h, high to low.
Each volume: dn/dt = sum F, P = n R T / V. S-200 and D-220 hold their pressure; atmosphere and flare
are Pa. Heun steps of at most 1.5 process-s; a step is split further only where a small volume
(the cavity) would otherwise ring, so the vent of F-210 alone runs at the full 1.5 process-s (C12).
Below DP_LIN_KPA of difference the law turns linear (continuous), so the gain stays finite at
equilibrium; it changes the vent only below Pa + DP_LIN_KPA.
"""

import math
import random

R, T, PA = 8.314, 293.0, 101.0  # kPa m3/(kmol K), K, kPa abs
RT = R * T
MAX_STEP_PROCESS_S = 1.5
DP_LIN_KPA = 0.5
TRAVEL_PCT_PER_S = 10.0  # 10 process-s end to end
PSV_OPEN_KPA, PSV_CLOSE_KPA = 2300.0, 2200.0
HEATER_FRAC_PER_S = 1e-4  # E-215 on: moles-equivalent rise in F-210 per process-s (plan cases only)
NOISE_FRAC = 0.001  # +-0.1 % of span
DROPOUT_CYCLE_PROCESS_S = 10.0

VOLUMES = {"C-202": 0.05, "F-210": 2.0}  # m3
SOURCES = {"S-200": 2000.0, "D-220": 1500.0}  # kPa abs, constant
# valve: (upstream node, downstream node, Cv in kmol/h per kPa, normal state %)
# VV-213 Cv: venting F-210 from 2000 to 102 kPa takes acosh(2000/101) - acosh(102/101) over
# a = R T Cv / (V 3600) = 298.7 process-s (~5 process-min).
VALVES = {
    "XV-201": ("S-200", "C-202", 0.1, 100.0),
    "BV-202": ("C-202", "atm", 0.01, 0.0),
    "XV-203": ("C-202", "F-210", 0.1, 100.0),
    "VV-213": ("F-210", "atm", 0.035, 0.0),
    "PSV-214": ("F-210", "flare", 0.2, 0.0),
    "XV-204": ("F-210", "D-220", 0.1, 100.0),
    "XV-231": ("D-220", "L-230", 0.1, 100.0),  # dead-end branch: never carries flow
}
COMMANDED = ("XV-201", "BV-202", "XV-203", "VV-213", "XV-204", "XV-231")
SPANS = {"PT-200": 2500.0, "PT-202": 2500.0, "PT-211": 2500.0, "PT-212": 2500.0, "FT-213": 100.0}
GAUGE_AT = {"PT-200": "S-200", "PT-202": "C-202", "PT-211": "F-210", "PT-212": "F-210"}


def law(cv: float, x: float, p_up: float, p_dn: float) -> float:
    """Signed flow a->b (kmol/h); linear below DP_LIN_KPA so equilibrium has a finite gain."""
    d = p_up * p_up - p_dn * p_dn
    floor = (p_up + p_dn) * DP_LIN_KPA
    return cv * x / 100 * d / math.sqrt(max(abs(d), floor, 1e-12))


class GasLine:
    def __init__(self, seed: int | None = None, rng: random.Random | None = None):
        self.rng = rng or random.Random(seed)
        self.t = 0.0  # process s
        self.src = dict(SOURCES)
        self.pos = {v: VALVES[v][3] for v in VALVES}
        self.cmd = {v: VALVES[v][3] for v in COMMANDED}
        self.leak = {v: 0.0 for v in VALVES}
        self.stuck = {v: False for v in VALVES}
        self.flow_scale = {v: 1.0 for v in VALVES}
        self.heater_on = False
        self.sensor = {tag: {"mode": 0, "severity": 0.0, "onset": 0.0, "held": None} for tag in SPANS}
        self.fb_fault = {v: {"mode": 0, "severity": 0.0, "held": None} for v in COMMANDED}
        self.n = {v: self._steady_p(v) * vol / RT for v, vol in VOLUMES.items()}
        self.last = self.measure()

    def _steady_p(self, vol: str) -> float:
        """Normal operation: S-200 -> XV-201 -> C-202 -> XV-203 -> F-210 -> XV-204 -> D-220 in series."""
        chain = [("XV-201", "C-202"), ("XV-203", "F-210"), ("XV-204", None)]
        total = sum(1 / VALVES[v][2] ** 2 for v, _ in chain)
        ps, pd = self.src["S-200"], self.src["D-220"]
        p2 = ps * ps
        for v, node in chain:
            p2 -= (ps * ps - pd * pd) / VALVES[v][2] ** 2 / total
            if node == vol:
                return math.sqrt(p2)
        raise KeyError(vol)

    # ---- state -----------------------------------------------------------------------------
    def p(self, node: str, n: dict | None = None) -> float:
        if node in VOLUMES:
            return (n or self.n)[node] * RT / VOLUMES[node]
        if node in self.src:
            return self.src[node]
        if node == "L-230":
            return self.src["D-220"]  # dead end, at its header's pressure
        return PA  # atm, flare

    def opening(self, v: str) -> float:
        return max(self.pos[v], self.leak[v]) * self.flow_scale[v]

    def flows(self, n: dict | None = None) -> dict[str, float]:
        """kmol/h through each valve, positive in the a -> b direction of VALVES."""
        return {v: law(cv, self.opening(v), self.p(a, n), self.p(b, n)) for v, (a, b, cv, _) in VALVES.items()}

    def _rates(self, n: dict) -> dict[str, float]:
        dn = {v: 0.0 for v in VOLUMES}
        for v, f in self.flows(n).items():
            a, b = VALVES[v][:2]
            if a in dn:
                dn[a] -= f / 3600
            if b in dn:
                dn[b] += f / 3600
        if self.heater_on:
            dn["F-210"] += HEATER_FRAC_PER_S * n["F-210"]
        return dn

    def _stiffness(self) -> float:
        """Largest d(dP/dt)/dP over the volumes (1/process-s), for the sub-step count."""
        worst = 0.0
        for vol, size in VOLUMES.items():
            g = 0.0
            for v, (a, b, cv, _) in VALVES.items():
                if vol in (a, b):
                    pa_, pb_ = self.p(a), self.p(b)
                    mine = pa_ if vol == a else pb_
                    g += cv * self.opening(v) / 100 * 2 * mine / math.sqrt(max(abs(pa_ * pa_ - pb_ * pb_), (pa_ + pb_) * DP_LIN_KPA))
            worst = max(worst, RT / (size * 3600) * g)
        return worst

    # ---- time ------------------------------------------------------------------------------
    def step(self, dt: float) -> None:
        """Advance dt process-s in steps of at most MAX_STEP_PROCESS_S."""
        while dt > 1e-12:
            h = min(dt, MAX_STEP_PROCESS_S)
            self._move_valves(h)
            m = max(1, math.ceil(h * self._stiffness()))
            for _ in range(m):
                self._heun(h / m)
            self.t += h
            dt -= h
            self.last = self.measure()

    def _heun(self, h: float) -> None:
        k1 = self._rates(self.n)
        mid = {v: max(self.n[v] + h * k1[v], 0.0) for v in self.n}
        k2 = self._rates(mid)
        self.n = {v: max(self.n[v] + h * (k1[v] + k2[v]) / 2, 0.0) for v in self.n}

    def _move_valves(self, h: float) -> None:
        for v in COMMANDED:
            if not self.stuck[v]:
                d = self.cmd[v] - self.pos[v]
                self.pos[v] += max(-TRAVEL_PCT_PER_S * h, min(TRAVEL_PCT_PER_S * h, d))
        pf = self.p("F-210")
        if pf > PSV_OPEN_KPA:
            self.pos["PSV-214"] = 100.0
        elif pf < PSV_CLOSE_KPA:
            self.pos["PSV-214"] = 0.0

    # ---- operator and faults (eval only) -------------------------------------------------------
    def command(self, valve: str, pct: float) -> None:
        self.cmd[valve] = 100.0 if pct >= 50 else 0.0

    def set(self, key: str, value: float) -> None:
        """Faults and boundary changes: '<PT>.fault_mode' (1 frozen, 2 drift per process-hour, 4 dropout
        fraction), '<PT>.fault_severity', '<V>.pos_fault_mode' (1 frozen, 2 offset, 3 fixed), '<V>.pos_fault_severity',
        '<V>.leak_pct', '<V>.stuck', '<V>.flow_scale', 'S-200.pressure_kpa', 'D-220.pressure_kpa', 'E-215.on'."""
        tag, attr = key.rsplit(".", 1)
        if attr == "fault_mode":
            s = self.sensor[tag]
            s.update(mode=int(value), onset=self.t, held=self.last[f"{tag}.PV"])
        elif attr == "fault_severity":
            self.sensor[tag]["severity"] = float(value)
        elif attr == "pos_fault_mode":
            self.fb_fault[tag].update(mode=int(value), held=self.last[f"{tag}.FB"])
        elif attr == "pos_fault_severity":
            self.fb_fault[tag]["severity"] = float(value)
        elif attr == "leak_pct":
            self.leak[tag] = float(value)
        elif attr == "stuck":
            self.stuck[tag] = bool(value)
        elif attr == "flow_scale":
            self.flow_scale[tag] = float(value)
        elif attr == "pressure_kpa":
            self.src[tag] = float(value)
        elif key == "E-215.on":
            self.heater_on = bool(value)
        else:
            raise KeyError(key)

    # ---- what the instruments show ---------------------------------------------------------------
    def _true_pv(self, tag: str) -> float:
        return self.flows()["VV-213"] if tag == "FT-213" else self.p(GAUGE_AT[tag])

    def _pv(self, tag: str) -> float:
        span, s = SPANS[tag], self.sensor[tag]
        if s["mode"] == 1:
            return s["held"]
        v = self._true_pv(tag)
        if s["mode"] == 2:
            v += s["severity"] * (self.t - s["onset"]) / 3600
        if s["mode"] == 4 and (self.t - s["onset"]) % DROPOUT_CYCLE_PROCESS_S < s["severity"] * DROPOUT_CYCLE_PROCESS_S:
            return 0.0
        v += self.rng.uniform(-1, 1) * NOISE_FRAC * span
        return min(max(v, 0.0), span)

    def _fb(self, v: str) -> float:
        f = self.fb_fault[v]
        if f["mode"] == 1:
            return f["held"]
        if f["mode"] == 3:
            return f["severity"]
        x = self.pos[v]
        sw = 0.0 if x <= 0.0 else 100.0 if x >= 100.0 else 50.0  # limit switches; 50 = neither made
        return min(max(sw + f["severity"], 0.0), 100.0) if f["mode"] == 2 else sw

    def measure(self) -> dict[str, float]:
        out = {f"{tag}.PV": self._pv(tag) for tag in SPANS}
        for v in COMMANDED:
            out[f"{v}.FB"] = self._fb(v)
            out[f"{v}.CMD"] = self.cmd[v]
        return out

    def truth(self) -> dict:
        f = self.flows()
        return {"t_process_s": self.t,
                "pressure_kpa_abs": {k: self.p(k) for k in (*VOLUMES, *SOURCES)},
                "position_pct": dict(self.pos), "command_pct": dict(self.cmd),
                "flow_kmol_h": f,
                # into F-210 through each line (unsafe if above 1 % of the line's full-open flow)
                "inflow_f210_kmol_h": {"XV-203": max(f["XV-203"], 0.0), "XV-204": max(-f["XV-204"], 0.0)},
                "faults": {"sensor": self.sensor, "feedback": self.fb_fault, "leak_pct": self.leak,
                           "stuck": self.stuck, "flow_scale": self.flow_scale, "heater_on": self.heater_on},
                "measured": self.last}
