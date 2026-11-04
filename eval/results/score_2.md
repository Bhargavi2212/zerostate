# Score: batch 2

- Engine: **full engine (live + process + camera)**
- Seal hash: `c1a2f5167a9314d6c329f1d78e27140068540840d66dfcc654aa93dba7bcc0f4`
- Plan hash: `63e1519c52f653b2607444e39baa63973b27cd867ec45c056d017f26e5f1bbc4`
- Scored episodes: 35

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
| Dangerous misses, primary | 0/35 (upper bound ≈ 3/n = 0.09; Wilson 95 % CI 0–0.10) |
| Dangerous misses, secondary | 0/35 (upper bound ≈ 3/n = 0.09; Wilson 95 % CI 0–0.10) |
| Missed faults (fault, NO_DISCREPANCY, no condition met), primary | 0/20 |
| False blocks on clean episodes (BLOCKED or ESCALATED) | 0/15 (upper bound ≈ 3/n = 0.20; Wilson 95 % CI 0–0.20) |
| — of which BLOCKED / ESCALATED | 0 / 0 |
| ZeroState decided on | 35 of 35 (whole job in 20) |
| INVALID entries | 0/35 (attempts: 0 INVALID of 35) |
| Baseline gauge_rule: decided on | 35 of 35 (whole job in 20) |
| Baseline gauge_rule: dangerous misses, primary | 0/35 (upper bound ≈ 3/n = 0.09; Wilson 95 % CI 0–0.10) |
| Baseline gauge_rule: dangerous misses, secondary | 0/35 (upper bound ≈ 3/n = 0.09; Wilson 95 % CI 0–0.10) |
| Baseline gauge_rule: primary misses by scenario | none |
| Baseline gauge_rule: secondary misses by scenario | none |
| Baseline gauge_rule: false blocks | 0/15 (upper bound ≈ 3/n = 0.20; Wilson 95 % CI 0–0.20) |

## Like for like: the 20 episodes where every system saw the whole job

In the other episodes ZeroState blocked early, the job stopped there, and a baseline judged only that early state.

| System | Dangerous misses, primary | Dangerous misses, secondary |
|---|---|---|
| ZeroState | 0/20 (upper bound ≈ 3/n = 0.15; Wilson 95 % CI 0–0.16) | 0/20 (upper bound ≈ 3/n = 0.15; Wilson 95 % CI 0–0.16) |
| Baseline gauge_rule | 0/20 (upper bound ≈ 3/n = 0.15; Wilson 95 % CI 0–0.16) | 0/20 (upper bound ≈ 3/n = 0.15; Wilson 95 % CI 0–0.16) |

Labels from truth (descriptive for BLOCKED / ESCALATED):

- primary: clean 15, fault, below hazard limits 10, unsafe 10
- secondary: clean 15, fault, below hazard limits 10, unsafe 10

## Per scenario

| Scenario | n | BLOCKED | ESCALATED | NO_DISCREPANCY | match | notes |
|---|---|---|---|---|---|---|
| S0 | 15 | 0 | 0 | 15 | 15/15 |  |
| S13 | 5 | 5 | 0 | 0 | 5/5 |  |
| S7 | 5 | 5 | 0 | 0 | 5/5 |  |
| S7-same | 5 | 5 | 0 | 0 | 5/5 |  |
| S8 | 5 | 5 | 0 | 0 | 5/5 |  |

## Hold detection by drawn leak size (counts; n ≤ 5 per bin, so no rates)

| Leak bin | n | BLOCKED | ESCALATED | NO_DISCREPANCY | LIVE-HOLD FAIL |
|---|---|---|---|---|---|
| 0.3-0.6 % | 0 | 0 | 0 | 0 | 0 |
| 0.6-0.9 % | 0 | 0 | 0 | 0 | 0 |
| 0.9-1.2 % | 0 | 0 | 0 | 0 | 0 |
| 1.2-1.5 % | 0 | 0 | 0 | 0 | 0 |

## Time to first BLOCKED or ESCALATED (process seconds from the fault event; episodes with a logged fault event only)

| Scenario | n | median | min | max |
|---|---|---|---|---|
| S8 | 5 | 69.2 | 68.1 | 70.1 |

## Severity at release (truth after NO_DISCREPANCY)

| Episode | max pressure kPa | max isolated-line flow % of full scale |
|---|---|---|
| S0_seed1011091684_20261104T015934 | 93.41 | 0.0 |
| S0_seed1876352260_20261104T020702 | 93.87 | 0.0 |
| S0_seed627673696_20261104T021550 | 94.03 | 0.0 |
| S0_seed1709801965_20261104T022228 | 94.1 | 0.0 |
| S0_seed1151298842_20261104T024930 | 94.15 | 0.0 |
| S0_seed60426185_20261104T030743 | 93.89 | 0.0 |
| S0_seed1849361298_20261104T031654 | 94.13 | 0.0 |
| S0_seed227718957_20261104T033910 | 93.52 | 0.0 |
| S0_seed204156906_20261104T035822 | 93.97 | 0.0 |
| S0_seed1846453526_20261104T041556 | 94.07 | 0.0 |
| S0_seed1995247948_20261104T042659 | 93.96 | 0.0 |
| S0_seed88445173_20261104T043350 | 93.94 | 0.0 |
| S0_seed1369092694_20261104T045249 | 93.92 | 0.0 |
| S0_seed181699700_20261104T050454 | 94.13 | 0.0 |
| S0_seed687600279_20261104T052334 | 94.09 | 0.0 |

## Camera vs data-only (idealised camera)

With-camera track blocked 20 of 35 (escalated 0); data-only blocked 20 of 35. The camera added a block where data-only gave NO_DISCREPANCY in 0; with-camera NO_DISCREPANCY where data-only did not: 0.

| Scenario | n | with-camera BLOCKED | data-only BLOCKED | camera track logged its own verdict |
|---|---|---|---|---|
| S0 | 15 | 0 | 0 | 0 |
| S13 | 5 | 5 | 5 | 0 |
| S7 | 5 | 5 | 5 | 0 |
| S7-same | 5 | 5 | 5 | 0 |
| S8 | 5 | 5 | 5 | 5 |

Coverage: 438 of 450 camera readings readable; no frame 0 (timeouts 0), model unavailable 0, located by the calibrated map 25, reads still pending at stop 0.

| Episode | camera timeouts |
|---|---|
| S0_seed1011091684_20261104T015934 | 0 |
| S0_seed1876352260_20261104T020702 | 0 |
| S0_seed627673696_20261104T021550 | 0 |
| S0_seed1709801965_20261104T022228 | 0 |
| S7-same_seed1303195242_20261104T023036 | 0 |
| S8_seed155989621_20261104T023450 | 0 |
| S13_seed1969389249_20261104T023839 | 0 |
| S7-same_seed739700797_20261104T024527 | 0 |
| S0_seed1151298842_20261104T024930 | 0 |
| S7-same_seed1870229617_20261104T025615 | 0 |
| S13_seed22487494_20261104T030114 | 0 |
| S0_seed60426185_20261104T030743 | 0 |
| S0_seed1849361298_20261104T031654 | 0 |
| S7-same_seed613598573_20261104T032417 | 0 |
| S13_seed1919072324_20261104T032856 | 0 |
| S8_seed5623454_20261104T033519 | 0 |
| S0_seed227718957_20261104T033910 | 0 |
| S7_seed1278157620_20261104T034714 | 0 |
| S13_seed2070322231_20261104T035145 | 0 |
| S0_seed204156906_20261104T035822 | 0 |
| S7_seed50230632_20261104T040550 | 0 |
| S7_seed1655100685_20261104T041137 | 0 |
| S0_seed1846453526_20261104T041556 | 0 |
| S8_seed1914382681_20261104T042312 | 0 |
| S0_seed1995247948_20261104T042659 | 0 |
| S0_seed88445173_20261104T043350 | 0 |
| S13_seed672731537_20261104T044147 | 0 |
| S8_seed649954990_20261104T044854 | 0 |
| S0_seed1369092694_20261104T045249 | 0 |
| S8_seed1470975726_20261104T050105 | 0 |
| S0_seed181699700_20261104T050454 | 0 |
| S7_seed1263244227_20261104T051135 | 0 |
| S7-same_seed693066144_20261104T051541 | 0 |
| S7_seed994113272_20261104T051943 | 0 |
| S0_seed687600279_20261104T052334 | 0 |

## Plan set

45/45 cases match their labels; false blocks on correct plans 0/15 (upper bound ≈ 3/n = 0.20; Wilson 95 % CI 0–0.20). Manifest plan entries without a result: none; results not in the manifest: none.

| Case | n | blocked | label match |
|---|---|---|---|
| PC0 | 15 | 0 | 15/15 |
| PC1 | 5 | 5 | 5/5 |
| PC2 | 5 | 5 | 5/5 |
| PC3 | 5 | 5 | 5/5 |
| PC4 | 5 | 5 | 5/5 |
| PC5 | 5 | 5 | 5/5 |
| PC6 | 5 | 5 | 5/5 |

## INVALID entries and episode problems

- none
