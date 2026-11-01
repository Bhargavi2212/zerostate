# ZeroState — claims ledger

Rule: a sentence may appear in the README, pitch or video only if it is in this table with status PASSING. Anything not passing at **Nov 3, 12:00 ET** is deleted from the submission — not reworded. Wording rules: PROJECT.md "never say" list.
Mechanism: `eval/claims.yaml` maps each claim id → required tests → eval result key → exact README sentence with placeholders. `eval/claims_audit.py` fails if a test is missing/failing, a result key is missing, or the README sentence differs from the rendered one.

| ID | Claim (exact wording) | Component | Proof | Status |
|---|---|---|---|---|
| C1 | ZeroState has no write code path to the plant and can reach only the PLC's Modbus port; the plant's IDS logged zero Modbus writes from it across all episodes, while the same rule caught the operator script's writes in every episode. | Adapters + network firewall | `tests/test_readonly.py`, `tests/test_firewall.py`, `tests/net/test_container_isolation.py`, `deploy/check_ids.ps1` | BUILT, evidence pending (Phase 1 gate) |
| C2 | Tested on P1 (GRFICS, Modbus) and P2 (our gas line, OPC UA); moving between them changed only plant files. | Envelope + adapters | CI diff test + `eval/run_benchmark.py` on both | NOT BUILT (withdrawn if P2 cut) |
| C3 | On X plans with errors planted from real incidents it flagged Y; it falsely blocked Z of W correct plans. | Plan checks | `eval/plan_benchmark.py` | NOT BUILT |
| C4 | A pressure reading is used as evidence only after it has tracked the depressurisation and agreed with an independent physics estimate. | LIVE-ALIVE, LIVE-RELATION | `tests/checks/test_alive.py`, `tests/checks/test_relation.py`, S1/S2/S3 episodes | BUILT, evidence pending (Phase 1 gate) |
| C5 | Across N pre-registered live episodes (data only) it had X dangerous misses (95% CI …), vs Y for the gauge rule and Z for Muse Spark alone; known blind spots listed. | Whole system | `eval/run_benchmark.py` + `eval/score.py` | NOT BUILT |
| C6 | On M clean episodes it falsely blocked K. | Whole system | same | NOT BUILT |
| C7 | SAM 3.1 + Muse Spark read plant displays with A% exact match on a sealed set of F frames (simulated camera). | Camera channel | `eval/read_accuracy.py` | NOT BUILT |
| C8 | In the patched simulator it blocked K of N episodes where valve position feedback lied, using physics relations (and, separately, the idealised camera). | LIVE-RELATION, LIVE-VALVE, LIVE-CAMERA | S8 episodes | NOT BUILT |
| C9 | Stale or frozen plant data never produces a pass. (Freeze detection relies on transmitter noise we add to the simulators; results say so.) | LIVE-QUALITY + freshness + gate | `tests/test_freshness.py`, `tests/checks/test_quality.py`, S12 episodes | BUILT, evidence pending (Phase 1 gate) |
| C10 | It never outputs "safe"; the model can only add a block; three refusals escalate; only a human signature closes. | Gate | `tests/test_gate.py` | NOT BUILT |
| C11 | Every verdict is in a hash-chained log and replays to the same verdict. | Audit | `tests/test_audit_chain.py`, `tests/test_replay.py` | BUILT, evidence pending (Phase 1 gate) |
| C12 | P2's simulator matches the analytic blowdown solution within E% (implementation check). | P2 plant | `eval/p2_validation.py` | NOT BUILT |
| C13 | Process rules: out-of-order steps, the same person installing and verifying, and temporary de-isolation are all caught. | Process checks | `tests/checks/test_sequence.py`, `tests/checks/test_independence.py`, `tests/checks/test_reset.py`, S7 | NOT BUILT |
| C14 | Muse Spark drafts an envelope from an isolation sheet with P/R field accuracy on n sheets; nothing runs until a person confirms it. | Importer | `tests/test_importer_gate.py`, `eval/importer_accuracy.py` | NOT BUILT |
| S-1 | (stretch) Third plant (WNTR). | — | — | NOT BUILT |
| S-2 | (stretch) Replay detection (S9). | — | — | NOT BUILT |

Model-attribution rule: every claim names which part does the work. Components with no claim and no test are not mentioned in the README.
