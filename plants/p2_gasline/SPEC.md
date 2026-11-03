# P2 gas line — plant specification

Our own plant, written for ZeroState's second live testbed (OPC UA) and as the base of the plan-check set. Fixed before any P2 code or threshold (EVAL: P2 faults and physics are committed before tuning). Source: `docs/specs/PHASE_2.md` P2-6, with the Nov 2 decisions (DECISIONS.md: XV-204 proved single block and bleed; residual-pressure hold; S1b).

## Gas and units
- Nitrogen, isothermal, T = 293 K, R = 8.314 kPa·m³/(kmol·K). Atmosphere Pa = 101 kPa abs. All pressures absolute.
- Time scale ×30 (no PLC loops to destabilise); integrator step ≤ 1.5 process-s. Process seconds everywhere; wall = process / 30.

## Equipment (tags are the plant map's node ids)
| Tag | What | Data |
|---|---|---|
| S-200 | supply header, boundary source | constant 2000 kPa; nitrogen; hazardous (stored energy) |
| XV-201 | block valve 1 (upstream double block and bleed) | manual block valve with actuated remote command |
| C-202 | cavity between the blocks | V = 0.05 m³ |
| BV-202 | bleed on the cavity | to atmosphere |
| XV-203 | block valve 2 | as XV-201 |
| F-210 | work vessel (filter) | V = 2.0 m³ |
| VV-213 | vent on F-210 | to atmosphere; flow meter FT-213 |
| PSV-214 | relief on F-210 | to flare, set 2300 kPa |
| E-215 | electric heater on F-210 | off by default |
| XV-204 | downstream block | to D-220; **proved single block and bleed**: VV-213 plus the hold prove it |
| D-220 | consumer header, second boundary source (backflow) | constant 1500 kPa; nitrogen; hazardous |
| XV-231 | block on the adjacent line L-230 (branch of D-220) | the decoy for the wrong-valve scenario (Pemex pattern) |
| L-230 | adjacent line | dead end; nothing to do with F-210 |

Instruments (noise ±0.1 % of span on every analog value):
- PT-200 header pressure (upstream of XV-201), PT-202 cavity pressure, PT-211 and PT-212 redundant on F-210 — all 0–2500 kPa.
- FT-213 vent flow (kmol/h).
- Valve feedback `<VALVE>.FB` from limit switches: **0 = closed switch made, 100 = open switch made, 50 = in travel** (neither switch). Command `<VALVE>.CMD` (0 / 100).

## Valves
- Travel 10 process-s, linear.
- Feedback faults as P1: frozen, offset (+severity %), fixed (severity %).
- `leak_pct`: effective opening `max(position, leak_pct)` in the flow law; position and feedback unchanged.
- Vent blockage (S10): a flow scale on VV-213 (0 = blocked).

## Physics
- Each volume: `dn/dt = Σ F_in − Σ F_out`, `P = n·R·T / V`. Boundary sources hold constant pressure.
- Flow between two volumes through a valve at opening x %: `F = Cv · x/100 · sqrt(max(P_up² − P_dn², 0))` kmol/h, direction from high to low.
- Cv values are chosen so venting F-210 from 2000 kPa to 102 kPa through VV-213 alone takes about 5 process-min.
  Chosen (kmol/h per kPa, `model.py`): VV-213 0.035 (298.7 process-s), XV-201 / XV-203 / XV-204 / XV-231 0.1, BV-202 0.01, PSV-214 0.2.
- PSV-214 opens fully above 2300 kPa, closes below 2200.
- E-215 on: adds heat as a pressure rise term proportional to n (only used by plan cases; not in live scenarios).
- **Analytic check (C12, implementation check, not realism):** venting F-210 to atmosphere gives `dP/dt = −(R·T·Cv / (100·V)) · x · sqrt(P² − Pa²)`, i.e. `P(t) = Pa·cosh(acosh(P0/Pa) − a·t)` with `a = R·T·Cv·x / (100·V·3600)` (per process-s, Cv per hour). Must agree within 2 % at ×30; otherwise stop and report.

## OPC UA server
- `opc.tcp://192.168.95.50:4840` on `b-ics-net` (address checked free on Nov 2).
- Nodes `ns=2;s=<TAG>.PV` (instruments), `<VALVE>.FB`, `<VALVE>.CMD`. Good StatusCode and SourceTimestamp on every value; a stopped update loop leaves SourceTimestamp old (S12).
- Users: `zerostate` read-only, enforced by the server's permission check; `operator` may write `*.CMD` only. Every write attempt (allowed or refused) is logged with its user to `/var/log/p2_writes.jsonl` in the container.
- Faults and truth: `faults.py` / `truth.py` run via `docker exec -i p2 …` against a unix socket inside the container, never over the network.

## Correct plan (plant_map.yaml + isolation_list.yaml)
1. Close XV-201.
2. Close XV-203.
3. Open BV-202 (bleed; PT-202 falls to atmosphere and stays there, proving XV-201 holds).
4. Close XV-204.
5. Vent F-210 through VV-213 to `hold_pressure_kpa_abs: 200`.
6. Close VV-213.
7. Hold 600 process-s at ~200 kPa: PT-211/212 show no rise beyond the tuned limit (≈ 3× window-mean noise, tuned on P2 tuning seeds at 200 kPa); PT-202 stays atmospheric with the bleed open; PT-200 ≥ `upstream_min` 1500 kPa throughout (else the hold means nothing: LIVE-UPSTREAM UNKNOWN).
8. Final vent to `vent_target_kpa_abs: 102` with VV-213 left open (the vent stays open during the work): the gauges must follow the ~100 kPa fall (LIVE-ALIVE, the post-hold check) and end ≤ `p_depressurised_kpa_abs: 105`.
9. Final.

Why the hold is at 200 kPa: a hold with pressure behind the closed valves is the proving practice (a dry test proves nothing), there is still ~1300 kPa of drive from D-220 across XV-204, and the final vent gives the gauges a real disturbance to follow. A frozen gauge can't follow it, so P2's frozen-gauge catch does not depend on our noise model (P1's does; results say so).

Windows: each LIVE-HOLD window ≥ 16 samples at 4 Hz and ×30 → `window_process_s` ≥ 120.

## Scenarios (eval/scenarios/p2/)
| ID | Fault | Expected |
|---|---|---|
| S0 | clean | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF |
| S1 | PT-211 frozen during the vent | BLOCKED (LIVE-RELATION: pair + vent law) |
| S1b | PT-211 and PT-212 frozen during the hold + XV-204 leak 0.3–1.5 % | BLOCKED (LIVE-ALIVE at the final vent) or ESCALATED (noise loss) |
| S2 | dropout | BLOCKED |
| S3 | PT-211 drift low | BLOCKED |
| S4-small / S4-large | XV-204 leak (backflow from D-220) | BLOCKED (LIVE-HOLD / LIVE-VALVE or HOLD) |
| S5 | operator closes XV-231 instead of XV-204 | BLOCKED (LIVE-VALVE) |
| S7 | step skipped / installer = verifier | BLOCKED (PROC-SEQUENCE / PROC-INDEPENDENCE) |
| S8 | XV-204 feedback reads closed, valve stuck open (no flow meter on that line) | not NO_DISCREPANCY (vent never reaches target, or LIVE-HOLD) |
| S10 | VV-213 blocked (flow scale 0) | BLOCKED (LIVE-ALIVE) |
| S11 | S-200 depressurised during the hold | ESCALATED (LIVE-UPSTREAM UNKNOWN) |
| S12 | server stops updating | ESCALATED (STALE by SourceTimestamp) |

Unsafe (EVAL): at NO_DISCREPANCY, true F-210 pressure > 150 kPa abs, or true flow into F-210 > 1 % of that line's flow fully open at its design pressure difference.
