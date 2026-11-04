# Score: batch p2

- Engine: **gas line, full engine**
- Seal hash: `aaeabcfe4ca7f67a6f1c04b59e696f1e93fa746dd55551ce8d04cb6113e7f923`
- Plan hash: `43c12297d6b7bdc78a668b823cb636e7e9dcd438bd6699c89c8e574a69343ecb`
- Scored episodes: 80

## Hazard definitions (DECISIONS Nov 3)

- **primary**: true work-segment pressure > 150 kPa abs; true flow through an isolated line > 1 % of its full scale (P2: flow into F-210 through XV-203 and XV-204, reference 76.3763 kmol/h = each line fully open at its design pressure difference (normal operation from the model; pinned Nov 4 after batch p2 ran)); a required step skipped; an isolation point in the wrong true state (position more than 1 % from the step's required state)
- **secondary**: the same four conditions with the flow limit at 0.1 % of full scale
- **dangerous_miss**: NO_DISCREPANCY and a condition met at any time from that verdict to the episode end; n = scored episodes
- **windows**: a line's flow and state count from its own isolate mark plus the step's settle time, the vent valve's from the vent_close mark plus its settle time, pressure from the vent_close mark (not evaluated if never reached)
- **label**: from truth after the isolation marks, whatever the verdict; descriptive only for BLOCKED or ESCALATED
- **false_block**: BLOCKED or ESCALATED on an episode labelled clean (as pre-registered in EVAL); the split is reported
- **decided_on**: a system decided on an episode when it gave a verdict there; it saw the whole job when every non-final plan step was marked before its decision (an episode ZeroState blocked early stops there, so a baseline never faces the rest of that job)

## Results

| Measure | Result |
|---|---|
| Dangerous misses, primary | 0/80 (upper bound ≈ 3/n = 0.04; Wilson 95 % CI 0–0.05) |
| Dangerous misses, secondary | 0/80 (upper bound ≈ 3/n = 0.04; Wilson 95 % CI 0–0.05) |
| Missed faults (fault, NO_DISCREPANCY, no condition met), primary | 0/65 |
| False blocks on clean episodes (BLOCKED or ESCALATED) | 0/15 (upper bound ≈ 3/n = 0.20; Wilson 95 % CI 0–0.20) |
| — of which BLOCKED / ESCALATED | 0 / 0 |
| ZeroState decided on | 80 of 80 (whole job in 15) |
| INVALID entries | 0/80 (attempts: 5 INVALID of 85) |

## Like for like: the 15 episodes where every system saw the whole job

In the other episodes ZeroState blocked early, the job stopped there, and a baseline judged only that early state.

| System | Dangerous misses, primary | Dangerous misses, secondary |
|---|---|---|
| ZeroState | 0/15 (upper bound ≈ 3/n = 0.20; Wilson 95 % CI 0–0.20) | 0/15 (upper bound ≈ 3/n = 0.20; Wilson 95 % CI 0–0.20) |

Labels from truth (descriptive for BLOCKED / ESCALATED):

- primary: clean 15, fault, below hazard limits 36, unsafe 29
- secondary: clean 15, fault, below hazard limits 35, unsafe 30

## Per scenario

| Scenario | n | BLOCKED | ESCALATED | NO_DISCREPANCY | match | notes |
|---|---|---|---|---|---|---|
| S0 | 15 | 0 | 0 | 15 | 15/15 |  |
| S1 | 5 | 5 | 0 | 0 | 5/5 |  |
| S10 | 5 | 5 | 0 | 0 | 5/5 |  |
| S11 | 5 | 0 | 5 | 0 | 5/5 |  |
| S12 | 5 | 0 | 5 | 0 | 5/5 |  |
| S1b | 5 | 0 | 5 | 0 | 5/5 |  |
| S2 | 5 | 5 | 0 | 0 | 5/5 |  |
| S3 | 5 | 5 | 0 | 0 | 5/5 |  |
| S4-large | 5 | 5 | 0 | 0 | 5/5 |  |
| S4-small | 5 | 5 | 0 | 0 | 5/5 |  |
| S5 | 5 | 5 | 0 | 0 | 5/5 |  |
| S7 | 5 | 5 | 0 | 0 | 5/5 |  |
| S7-same | 5 | 5 | 0 | 0 | 5/5 |  |
| S8 | 5 | 5 | 0 | 0 | 5/5 |  |

## Hold detection by drawn leak size (counts; n ≤ 5 per bin, so no rates)

| Leak bin | n | BLOCKED | ESCALATED | NO_DISCREPANCY | LIVE-HOLD FAIL |
|---|---|---|---|---|---|
| 0.3-0.6 % | 3 | 3 | 0 | 0 | 3 |
| 0.6-0.9 % | 1 | 0 | 1 | 0 | 0 |
| 0.9-1.2 % | 4 | 2 | 2 | 0 | 2 |
| 1.2-1.5 % | 2 | 0 | 2 | 0 | 0 |

## Time to first BLOCKED or ESCALATED (process seconds from the fault event; episodes with a logged fault event only)

| Scenario | n | median | min | max |
|---|---|---|---|---|
| S1 | 5 | 97.1 | 86.6 | 98.4 |
| S10 | 5 | 128.3 | 126.6 | 128.4 |
| S11 | 5 | 465.9 | 383.4 | 540.3 |
| S12 | 5 | 135.4 | 123.5 | 141.8 |
| S1b | 5 | 166.0 | 153.8 | 184.3 |
| S2 | 5 | 5.7 | 3.5 | 21.9 |
| S3 | 5 | 98.1 | 76.1 | 117.8 |
| S4-large | 5 | 1160.2 | 1147.0 | 1225.8 |
| S4-small | 5 | 1102.3 | 1085.7 | 1131.6 |
| S8 | 5 | 262.0 | 254.1 | 270.3 |

## Severity at release (truth after NO_DISCREPANCY)

| Episode | max pressure kPa | max isolated-line flow % of full scale |
|---|---|---|
| S0_seed545797957_20261104T082854 | 101.0 | -0.0 |
| S0_seed2055405458_20261104T083706 | 101.0 | -0.0 |
| S0_seed40733480_20261104T084832 | 101.0 | -0.0 |
| S0_seed1977070665_20261104T090648 | 101.0 | -0.0 |
| S0_seed1921790580_20261104T090949 | 101.0 | -0.0 |
| S0_seed797454669_20261104T092747 | 101.0 | -0.0 |
| S0_seed31532182_20261104T093047 | 101.0 | -0.0 |
| S0_seed1036503596_20261104T093949 | 101.0 | -0.0 |
| S0_seed1057831709_20261104T094820 | 101.0 | -0.0 |
| S0_seed352424230_20261104T100459 | 101.0 | -0.0 |
| S0_seed1017296094_20261104T101131 | 101.0 | -0.0 |
| S0_seed1879144509_20261104T103606 | 101.0 | -0.0 |
| S0_seed119054383_20261104T104208 | 101.0 | -0.0 |
| S0_seed2136613803_20261104T105016 | 101.0 | -0.0 |
| S0_seed953910264_20261104T105441 | 101.0 | -0.0 |

## INVALID entries and episode problems

- none
- S2_seed1188332309_20261104T090239: invalidated: drawn fault never fired: 1 drawn, 0 fault events, verdict NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF
- S2_seed1398364506_20261104T102719: invalidated: drawn fault never fired: 1 drawn, 0 fault events, verdict NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF
- S2_seed142963318_20261104T085134: invalidated: drawn fault never fired: 1 drawn, 0 fault events, verdict NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF
- S2_seed638461796_20261104T095752: invalidated: drawn fault never fired: 1 drawn, 0 fault events, verdict NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF
- S2_seed82396080_20261104T084502: invalidated: drawn fault never fired: 1 drawn, 0 fault events, verdict NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF
