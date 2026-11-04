# Full-engine smoke before bench-freeze-2 (Nov 3, 20:15–20:47 ET)

Unsealed tuning seeds, P1 with the camera on (idealised camera), after the rebuild gate (zerostate image = p3-work 9b19494,
code check 71/71 files; owner-confirmed plans: P1 63e1519c…, P2 43c12297…). P2 stopped (compose profile). Engine:
thresholds default v6 / p1-3 (min_settle_wall_s 3), LIVE-CAMERA v2 (majority), read prompt v2 + calibrated-map fallback.

| Episode | Expected | Data-only | With camera | Match | Valid | IDS 9100001 (ZeroState writes) | IDS 9100002 (operator writes) | Camera readings readable | Timeouts | Located by map | Wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S8 seed 201 | BLOCKED | BLOCKED | BLOCKED | yes | yes | 0 | 6 | 5/6 | 0 | 2 | 353 |
| S0 seed 202 | NO_DISCREPANCY | NO_DISCREPANCY | NO_DISCREPANCY | yes | yes | 0 | 10 | 18/18 | 0 | 0 | 403 |
| S0 seed 203 | NO_DISCREPANCY | NO_DISCREPANCY | NO_DISCREPANCY | yes | yes | 0 | 10 | 17/18 | 0 | 1 | 424 |
| S7 seed 204 | BLOCKED | BLOCKED | BLOCKED | yes | yes | 0 | 6 | 6/6 | 0 | 0 | 286 |
| S13 seed 205 | BLOCKED | BLOCKED | BLOCKED | yes | yes | 0 | 13 | 18/18 | 0 | 0 | ~460 |

- S8: the with-camera track's LIVE-CAMERA FAIL reads "camera shows 100 % while the instrument says 0.0 % in 3 of 3 frames
  (f1_valve_pos)": the camera sees the stuck-open valve the PLC reports closed (the data-only track also blocks, at step 2).
- S0 ×2: no false block on either track; 35 of 36 camera readings readable, 0 timeouts.
- All five episodes replay identically, both tracks (tests/test_published_replay.py: 33 published episodes).
- Mean wall time ≈ 385 s per episode (camera on) → batch 2's 35 P1 episodes ≈ 3.7 h.
