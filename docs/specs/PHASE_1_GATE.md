# Phase 1 — gate output

Run 2026-11-01 (UTC 17:40–19:10), branch `p1-work`, GRFICS patched image `zerostate/grfics-simulation:p1-1`
(changes A, B, D, E, F, G, H, I; C dropped), time scale ×10, thresholds `2+p1-1` (LIVE-QUALITY v2).

| # | Gate item | Result |
|---|---|---|
| 1 | Patched image running, `zs_patch_version = p1-1`; `docker compose config` shows no simulation build; image-match recorded (patch README: label `v1.3.3-2-g8d611b7`, `/app/modbus/*.py`, `run_all.sh`, `index.php` identical to the clone); `tests/live/test_patch.py` | **PASS** — live tests 8/8 (patch 5 incl. leak, operator net 3) |
| 2 | Time-scale decision recorded with stability numbers | **PASS** — ×10 (DECISIONS): AUTO ×1 sd 2.8 kPa, ×5 13.0, ×10 24.6 (steady, bounded; old 3× criterion failed at ×5 and ×10). Corrected criterion: manual-mode vent aligned on 2500 kPa, ×10 vs ×1 within 1.0 % at 1500/700/300/150/102 kPa, both 5–7 % faster than the simple physics model (`eval/results/timescale_2026-11-01.json`, `vent_fidelity_2026-11-01.json`; first absolute-time attempt kept as `…_absolute_time.json`) |
| 3 | `pytest -q` offline green incl. operator, path rule, 5 rules + invariance, models (steps), gate, session, audit chain, replay | **PASS** — 93 passed |
| 4 | `docker exec -u 0 zerostate pytest -m net -q` 15/15; zs-operator cannot reach .45:80 / :55555 | **PASS** — 15 passed (as root); operator net 3/3 |
| 5 | Every smoke row matches its expected verdict; every episode has a valid postflight | **PASS** — 13/13 (S0 ×4 incl. a final-image confirmation run) |
| 6 | `zs replay` reproduces every smoke episode's verdict; `zs audit verify` passes | **PASS** — all 13 replay identical, all chains ok |
| 7 | `check_ids` per episode: 9100001 = 0, 9100002 > 0 | **PASS** — 0 ZeroState writes in every episode; operator writes 2–9 per episode |
| 8 | `/ponytail-review branch` findings fixed | **PASS** — 4 findings (runner cleanup on failure; operator errors ignored; unbounded session buffer; silent monitor crash) fixed in `2c779a4` with tests; final S0 seed 4 re-run on that image |

## What the smoke run found and fixed (all on tuning seeds 0–999)
- Runner read step results with int keys while JSON returns strings → stalled after step 1 (plant drifted to 3200 kPa in manual). Fixed, regression test.
- S0 seed 2 false trip: a late poll carried a stale pressure; one-poll rate read 55 kPa/process-s (true max ≈ 14). LIVE-QUALITY v1 → v2 (20 process-s rate baseline); proven not blunted: 2700 → 0 → 2700 kPa during the vent still fails with the 50 kPa floor switched off, in the rule and the live monitor. Monitor window reaches back the rate span; each valve judged only after its own settle.
- First S12 invalid: `supervisorctl stop modbus` left the device scripts running (no stopasgroup), so no comms loss happened. The runner now kills them and verifies every fault took effect; invalid episodes are marked, never counted.
- Docker Desktop dropped the Windows port-80 forward after a recreate: truth is read from inside the simulation container (VM clock, same as ZeroState's audit).
- Operator script shadowed the stdlib `operator` module inside its container: `PYTHONSAFEPATH=1`.

## Known limits (reported, not hidden)
- Freeze detection depends on our noise model; S1 is also caught by the valve law (RELATION), S1b by VALVE (its leak was above the 1.6 % cutoff), S12 by the host path rule.
- AUTO at ×10 oscillates (PLC tuned for real time); episodes run in manual where its loops are off. At ×10 the bumpless switch may copy purge open from the oscillation, so the plant can vent during steps 2–4 (S0 seed 3 / 4 vent times 74 / 81 process-s).
- Level dropout to 0 is not caught (level is not evidence for a vapour-side isolation).
- Plan and process checks are Phase 2; the P1 plan's own plan check is expected to BLOCK (control-valve-only isolation).

## Claims
C1, C4, C9, C11 → built, evidence pending (PASSING only via the Phase 3 claims audit).

## Raw output (final image)
```
### pytest -q (repo venv)
93 passed, 23 deselected in 3.87s

### live: patch, leak, operator net (host)
1 failed, 7 passed in 55.71s

### docker exec -u 0 zerostate pytest -m net -q
15 passed in 19.18s

### replay + audit verify + IDS per episode (final image)
S0_seed1_20261101T174920 | replay identical | chain ok; 18 events in S0_seed1_20261101T174920 | {"rotated":false,"9100001":0,"9100002":9}
S0_seed2_20261101T183158 | replay identical | chain ok; 18 events in S0_seed2_20261101T183158 | {"rotated":false,"9100001":0,"9100002":9}
S0_seed3_20261101T175819 | replay identical | chain ok; 18 events in S0_seed3_20261101T175819 | {"rotated":false,"9100001":0,"9100002":9}
S1_seed11_20261101T180250 | replay identical | chain ok; 14 events in S1_seed11_20261101T180250 | {"rotated":false,"9100001":0,"9100002":8}
S1b_seed12_20261101T183640 | replay identical | chain ok; 16 events in S1b_seed12_20261101T183640 | {"rotated":false,"9100001":0,"9100002":9}
S2_seed13_20261101T181009 | replay identical | chain ok; 16 events in S2_seed13_20261101T181009 | {"rotated":false,"9100001":0,"9100002":9}
S3_seed14_20261101T181353 | replay identical | chain ok; 14 events in S3_seed14_20261101T181353 | {"rotated":false,"9100001":0,"9100002":8}
S4_seed15_20261101T181823 | replay identical | chain ok; 8 events in S4_seed15_20261101T181823 | {"rotated":false,"9100001":0,"9100002":5}
S5_seed16_20261101T182128 | replay identical | chain ok; 8 events in S5_seed16_20261101T182128 | {"rotated":false,"9100001":0,"9100002":5}
S6_seed17_20261101T182418 | replay identical | chain ok; 6 events in S6_seed17_20261101T182418 | {"rotated":false,"9100001":0,"9100002":2}
S8_seed18_20261101T182645 | replay identical | chain ok; 8 events in S8_seed18_20261101T182645 | {"rotated":false,"9100001":0,"9100002":5}
S12_seed19_20261101T184743 | replay identical | chain ok; 18 events in S12_seed19_20261101T184743 | {"rotated":false,"9100001":0,"9100002":9}
S0_seed4_20261101T185842 | replay identical | chain ok; 18 events in S0_seed4_20261101T185842 | {"rotated":false,"9100001":0,"9100002":9}

### smoke table
| scenario | seed | rules_basis | expected | actual | match | valid | first_block | to_block_process_s | vent_to_105_process_s | min_hold_kpa | problems |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 | 1 | replayed-under-v2 | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF | True | True |  |  | 313 | 99.1 |  |
| S0 | 2 | live-under-v2 | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF | True | True |  |  | 313 | 93.8 |  |
| S0 | 3 | replayed-under-v2 | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF | True | True |  |  | 74 | 93.4 |  |
| S1 | 11 | replayed-under-v2 | BLOCKED/ESCALATED | BLOCKED | True | True | LIVE-QUALITY UNKNOWN + LIVE-RELATION FAIL | 78 | not reached |  |  |
| S1b | 12 | live-under-v2 | ESCALATED/BLOCKED | BLOCKED | True | True | LIVE-VALVE FAIL | 12 | 313 |  |  |
| S2 | 13 | replayed-under-v2 | BLOCKED | BLOCKED | True | True | LIVE-QUALITY FAIL | 14 | 278 |  |  |
| S3 | 14 | replayed-under-v2 | BLOCKED | BLOCKED | True | True | LIVE-RELATION FAIL | 114 | not reached |  |  |
| S4 | 15 | replayed-under-v2 | BLOCKED | BLOCKED | True | True | LIVE-VALVE FAIL | 66 |  |  |  |
| S5 | 16 | replayed-under-v2 | BLOCKED | BLOCKED | True | True | LIVE-VALVE FAIL | 88 |  |  |  |
| S6 | 17 | replayed-under-v2 | BLOCKED | BLOCKED | True | True | LIVE-VALVE FAIL | 20 |  |  |  |
| S8 | 18 | replayed-under-v2 | BLOCKED | BLOCKED | True | True | LIVE-VALVE FAIL | 66 |  |  |  |
| S12 | 19 | live-under-v2 | ESCALATED | ESCALATED | True | True | LIVE-QUALITY UNKNOWN | 161 | 311 | 95.4 |  |
| S0 | 4 | live-under-v2-final | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF | NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF | True | True |  |  | 81 | 93.5 |  |
smoke exit=0
```

### live tests after the noise-test fix
```
8 passed in 56.23s
```
