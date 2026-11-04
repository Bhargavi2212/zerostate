# Phase 2: gate output

Written Nov 4, 2026 (~07:00 ET), after batch p2 finished, on `p3-work` at `aa7988a`. Phase 2's work
(`p2-work`) was already merged into `main` through PR #9 before this gate was written, so items 1–2 and 8b
were run now, on the current code, not at the close of `p2-work`. The order (gate after batch p2's launch)
was Bhargavi's call on Nov 4.

| # | Gate item | Result |
|---|---|---|
| 1 | `pytest -q` green offline: client, plan rules, importer gate, camera, process rules, OPC UA adapter, P2 model (C12 analytic) | **PASS**: 433 passed, 43 deselected (`-m net` / live), at `aa7988a` |
| 2 | `pytest -m net` in ZeroState: PLC:502, proxy only to api.meta.ai, frames, P2 OPC UA; everything else blocked | **PASS**: `docker exec -e ZS_NET_P2=1 -u zs zerostate pytest -m net -q tests/net/test_container_isolation.py`: 25 passed (incl. `test_p2_opcua_reachable`, `test_zerostate_account_cannot_write_p2`, `test_proxy_tunnels_only_to_the_meta_api_with_tls_end_to_end`, `test_proxy_refuses_everything_else`). The two P2 tests also passed as batch p2's launch gate (logged in its `progress.jsonl`, both launches and the S2 re-run) |
| 3 | Plan benchmark has run; P1's real plan BLOCKED by PLAN-SOFTWARE/TYPE | **PASS**: batch 2 plan set (sealed): 45/45 cases match their labels, 30/30 planted errors blocked, 0/15 correct plans blocked (`eval/results/score_2.json` `plan_set`). P1's real plan fails exactly PLAN-SOFTWARE and PLAN-TYPE (`tests/test_build.py:77`) |
| 4 | Importer accuracy for all three routes, with 0 invented points | **FAIL (reported, not reworked)**: text precision 0.951 / recall 0.97 with **1 invented point** (case t02: the purge vent valve listed as an isolation point); image 1.0 / 1.0; CSV 1.0 / 0.834 (t02 and s05 refused on an empty tag). `eval/results/importer_2026-11-04.json`. The t02 draft could not be confirmed (the confirm screen flagged the row and the plan would not merge until corrected); no message named the cause. C14 is NOT PASSING in the claims audit. The message fix comes after the measured run and is labelled so |
| 5 | Camera accuracy (C7), plus measured camera lag | **PARTIAL**: C7 measured: 398 of 400 valve displays read within 1 % (`eval/results/read_2026-11-03.json`; claims audit PASSING). Camera lag **not measured**: `camera_lag_max_wall_s: 5` is still the start value (the 3D page polls every 3 s). Batch 2 camera coverage: 438 of 450 readings readable, 0 timeouts (`score_2.json` `camera.coverage`) |
| 6 | Voice result recorded (pass, or fallback decided) | **RECORDED, bar not met**: Muse Voice Transcribe → rule parser, 3 runs: 16/20 (0 wrong-step), 18/20 (2 wrong-step: two clips saved under each other's names), final run 3 15/20 (0 wrong-step); bar ≥ 18/20 and 0 wrong-step. `eval/results/voice_runs.md`. No browser speech fallback (PHASE_3 D3) |
| 7 | P2: smoke passes and C12 passes, or the cut is recorded | **PASS**: smoke 7/7 match and valid on the rebuilt images (tuning seeds 401–407, ZeroState P2 writes 0; `eval/results/smoke_p2_2026-11-04.md`, episodes in `eval/results/smoke/p2/`). C12: 0.0129 % max error against the analytic blowdown (`eval/results/p2_validation_2026-11-03.json`). Batch p2 then ran: 80/80 entries valid (below) |
| 8 | Freeze tag, sealed hash committed before the first scoring episode, ≥ 1 valid scoring episode before 22:30 | **PASS** (per-batch names since DECISIONS Nov 2): `bench-freeze-p1` and `eval/sealed_hash_p1.txt` in one commit `0ba9dd8` at 21:53:52 Nov 2; first scoring episode valid at 21:57:31 (S6, `zs-bench` progress) |
| 8b | `docs/API.md` + `docs/BUNDLE.md` committed; API contract tests pass; `zs-api` reaches only the proxy; a bundle validates | **PASS**: both docs committed; `tests/test_api_contract.py` and `tests/test_bundle.py` (export → load → schema validates) in item 1; `docker exec zs-api pytest -m net -q tests/net/test_api_isolation.py`: 10 passed (proxy reachable, everything else unreachable, allowlist not changeable, audit log read-only) |
| 9 | `/ponytail-review branch` findings fixed | **NOT RUN** for `p2-work` as its own step; `p2-work` was merged without it. The Phase 3 review (`/ponytail-review branch` on `p3-work`) is the next review point |

## Stop-and-report items hit
- **A model route invented an isolation point** (importer text route, t02). Reported above and in the claims audit; the prompt was not changed before the measured run.
- None of the others: the frame service renders headless; the Meta API answers through the proxy; P2's analytic check is within 2 % (0.0129 %); `zerostate` cannot write P2 (item 2); the benchmark started on its frozen tag before 22:30.

## Batch p2 (record; scoring pending)
- Sealed manifest `manifest_p2.json`, hash committed in `eval/sealed_hash_p2.txt` before launch; unchanged throughout.
- After `bench-freeze-p2`, tuning seeds 301–317 found engine and harness bugs, fixed in `bench-freeze-p2b` (DECISIONS Nov 4: LIVE-VALVE v2, LIVE-ALIVE v3, P2 thresholds p2-2, ×10, the eval operator stamps its writes). No sealed seed was looked at before launch.
- Launched 03:27:34 Nov 4 with N = 80 (raw 178, cap 80; logged before launch). 80 entries ran, all valid by the runner's checks then; 75 matched.
- The 5 misses were all S2, and the fault never fired in any of them (`at_step: [5, 6, 7]` matched no step). The runner now marks an episode with an unfired drawn fault INVALID (61881ef). The same rule flags 0 in batch p1 and batch 2.
- The 5 S2 attempts got `invalidated` records, and the same 5 sealed seeds ran once from `bench-freeze-p2c` (06:27–06:35; ZeroState code identical to p2b): each fault fired once, and all 5 were BLOCKED by LIVE-QUALITY (PT-211 = 0, outside 50–3200 kPa). Final: 80/80 entries valid, 85 attempts, 5 invalidated (DECISIONS Nov 4).
- `score.py` has no P2 hazard labelling yet: the P2 flow reference ("full-open at design ΔP", EVAL) has no pinned numbers. Scoring batch p2 waits on that.

## Claims (claims audit, Nov 4 ~07:00)
PASSING: C1 (batch p1), C3, C4, C5.p1, C6.p1, C6.2, C7, C8.p1, C8.2, C9, C10, C11, C12, C13. NOT PASSING: C14 (1 invented point, as measured); C1.p2, C2, C5.p2, C6.p2 (no `score_p2.json` yet).
