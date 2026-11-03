# Score: batch p1

- Engine: **live checks only (Phase 1 engine)**
- Seal hash: `b27ca175c973ebc262fb0d40a50411eb31df1ea9a0a1d8eaa26d84529b7d866a`
- Plan hash: `89adfcf4fbb0a8e2b058c02ceed5d879d0a72312da92024bf967c8aec14f2a92`
- Scored episodes: 65

## Hazard definitions (DECISIONS Nov 3)

- **primary**: true work-segment pressure > 150 kPa abs; true flow through an isolated line > 1 % of its full scale (P1 scale_max: f1 1000, f2 500, purge 2000, product 500); a required step skipped; an isolation point in the wrong true state (position more than 1 % from the step's required state)
- **secondary**: the same four conditions with the flow limit at 0.1 % of full scale
- **dangerous_miss**: NO_DISCREPANCY and a condition met at any time from that verdict to the episode end; n = scored episodes
- **windows**: a line's flow and state count from its own isolate mark plus the step's settle time, the vent valve's from the vent_close mark plus its settle time, pressure from the vent_close mark (not evaluated if never reached)
- **label**: from truth after the isolation marks, whatever the verdict; descriptive only for BLOCKED or ESCALATED
- **false_block**: BLOCKED or ESCALATED on an episode labelled clean (as pre-registered in EVAL); the split is reported
- **decided_on**: a system decided on an episode when it gave a verdict there; it saw the whole job when every non-final plan step was marked before its decision (an episode ZeroState blocked early stops there, so a baseline never faces the rest of that job)

## Results

| Measure | Result |
|---|---|
| Dangerous misses, primary | 0/65 (upper bound ≈ 3/n = 0.05; Wilson 95 % CI 0–0.06) |
| Dangerous misses, secondary | 0/65 (upper bound ≈ 3/n = 0.05; Wilson 95 % CI 0–0.06) |
| Missed faults (fault, NO_DISCREPANCY, no condition met), primary | 0/49 |
| False blocks on clean episodes (BLOCKED or ESCALATED) | 1/16 (Wilson 95 % CI 0.01–0.28) |
| — of which BLOCKED / ESCALATED | 1 / 0 |
| ZeroState decided on | 65 of 65 (whole job in 27) |
| INVALID entries | 0/65 (attempts: 0 INVALID of 65) |
| Baseline gauge_rule: decided on | 65 of 65 (whole job in 27) |
| Baseline gauge_rule: dangerous misses, primary | 0/65 (upper bound ≈ 3/n = 0.05; Wilson 95 % CI 0–0.06) |
| Baseline gauge_rule: dangerous misses, secondary | 11/65 (Wilson 95 % CI 0.10–0.28) |
| Baseline gauge_rule: primary misses by scenario | none |
| Baseline gauge_rule: secondary misses by scenario | S12 1, S1b 5, S4-small 5 |
| Baseline gauge_rule: false blocks | 1/16 (Wilson 95 % CI 0.01–0.28) |
| Baseline muse_alone: decided on | 65 of 65 (whole job in 27) |
| Baseline muse_alone: dangerous misses, primary | 0/65 (upper bound ≈ 3/n = 0.05; Wilson 95 % CI 0–0.06) |
| Baseline muse_alone: dangerous misses, secondary | 0/65 (upper bound ≈ 3/n = 0.05; Wilson 95 % CI 0–0.06) |
| Baseline muse_alone: primary misses by scenario | none |
| Baseline muse_alone: secondary misses by scenario | none |
| Baseline muse_alone: false blocks | 7/16 (Wilson 95 % CI 0.23–0.67) |

## Like for like: the 27 episodes where every system saw the whole job

In the other episodes ZeroState blocked early, the job stopped there, and a baseline judged only that early state.

| System | Dangerous misses, primary | Dangerous misses, secondary |
|---|---|---|
| ZeroState | 0/27 (upper bound ≈ 3/n = 0.11; Wilson 95 % CI 0–0.12) | 0/27 (upper bound ≈ 3/n = 0.11; Wilson 95 % CI 0–0.12) |
| Baseline gauge_rule | 0/27 (upper bound ≈ 3/n = 0.11; Wilson 95 % CI 0–0.12) | 6/27 (Wilson 95 % CI 0.11–0.41) |
| Baseline muse_alone | 0/27 (upper bound ≈ 3/n = 0.11; Wilson 95 % CI 0–0.12) | 0/27 (upper bound ≈ 3/n = 0.11; Wilson 95 % CI 0–0.12) |

Labels from truth (descriptive for BLOCKED / ESCALATED):

- primary: clean 16, fault, below hazard limits 34, unsafe 15
- secondary: clean 16, fault, below hazard limits 23, unsafe 26

## Per scenario

| Scenario | n | BLOCKED | ESCALATED | NO_DISCREPANCY | match | notes |
|---|---|---|---|---|---|---|
| S0 | 15 | 0 | 0 | 15 | 15/15 |  |
| S1 | 5 | 5 | 0 | 0 | 5/5 | seed 260352266: fault never injected: the session ended (BLOCKED) before the fault's time, so truth labels it clean and a block counts as a false block; first finding: LIVE-VALVE: commanded state wrong: manual_mode is not 1 |
| S12 | 5 | 0 | 5 | 0 | 5/5 |  |
| S1b | 5 | 1 | 4 | 0 | 4/5 | seed 233000811: caught by flow before the hold: drawn leak 1.461 %, measured f1_flow = 10.1; expected ESCALATED, got BLOCKED |
| S2 | 5 | 5 | 0 | 0 | 5/5 |  |
| S3 | 5 | 5 | 0 | 0 | 5/5 |  |
| S4-large | 5 | 5 | 0 | 0 | 5/5 |  |
| S4-small | 5 | 5 | 0 | 0 | 5/5 |  |
| S5 | 5 | 5 | 0 | 0 | 5/5 |  |
| S6 | 5 | 5 | 0 | 0 | 5/5 |  |
| S8 | 5 | 5 | 0 | 0 | 5/5 |  |

## Hold detection by drawn leak size (counts; n ≤ 5 per bin, so no rates)

| Leak bin | n | BLOCKED | ESCALATED | NO_DISCREPANCY | LIVE-HOLD FAIL |
|---|---|---|---|---|---|
| 0.3-0.6 % | 2 | 1 | 1 | 0 | 1 |
| 0.6-0.9 % | 3 | 1 | 2 | 0 | 1 |
| 0.9-1.2 % | 3 | 2 | 1 | 0 | 2 |
| 1.2-1.5 % | 2 | 2 | 0 | 0 | 1 |

## Time to first BLOCKED or ESCALATED (process seconds from the fault event; episodes with a logged fault event only)

| Scenario | n | median | min | max |
|---|---|---|---|---|
| S1 | 4 | 90.4 | 77.2 | 96.7 |
| S12 | 5 | 157.8 | 139.2 | 173.1 |
| S1b | 5 | 71.6 | 16.6 | 71.6 |
| S2 | 5 | 19.0 | 11.6 | 49.1 |
| S3 | 5 | 96.6 | 96.0 | 109.2 |
| S4-large | 5 | 64.1 | 64.1 | 66.7 |
| S4-small | 5 | 1263.4 | 1226.8 | 1276.7 |
| S8 | 5 | 64.1 | 64.1 | 66.7 |

## Severity at release (truth after NO_DISCREPANCY)

| Episode | max pressure kPa | max isolated-line flow % of full scale |
|---|---|---|
| S0_seed593156928_20261103T030337 | 94.21 | 0.0 |
| S0_seed630899265_20261103T033644 | 94.17 | 0.0 |
| S0_seed448148710_20261103T034143 | 94.03 | 0.0 |
| S0_seed947938994_20261103T041208 | 94.11 | 0.0 |
| S0_seed1205025384_20261103T042121 | 94.22 | 0.0 |
| S0_seed2009026901_20261103T050451 | 93.5 | 0.0 |
| S0_seed1288313240_20261103T054040 | 94.38 | 0.0 |
| S0_seed1591802094_20261103T055240 | 94.2 | 0.0 |
| S0_seed941169427_20261103T055723 | 94.04 | 0.0 |
| S0_seed2029860766_20261103T061531 | 94.44 | 0.0 |
| S0_seed658491427_20261103T062513 | 94.24 | 0.0 |
| S0_seed1464721829_20261103T063302 | 94.4 | 0.0 |
| S0_seed1372473534_20261103T063726 | 93.95 | 0.0 |
| S0_seed29244592_20261103T064227 | 94.2 | 0.0 |
| S0_seed1184053442_20261103T071508 | 94.02 | 0.0 |

## INVALID entries and episode problems

- none
