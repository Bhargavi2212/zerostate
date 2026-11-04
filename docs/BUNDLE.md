# Episode bundle (version 2)

What the public replay viewer (Phase 3, `site/` on Vercel, static) and the API's replay mode (`zs api --replay <bundle_dir>`, docs/API.md) read. One file per episode: `bundle.json.gz` (gzipped JSON), written by `eval/tools/export_bundle.py` from a published episode (`eval/results/episodes/<episode>/` or `eval/results/bench/<batch>/<episode>/`). Schema in code: `Bundle` in `eval/tools/export_bundle.py` (pydantic, `extra="forbid"`); `tests/test_bundle.py` exports a real episode, loads it back and validates it.

Nothing live is hosted publicly: a bundle holds logged data only. No key, no API address, **no images**: camera readings carry frame hashes only, never frames or crops. A bundle containing a key-like string is refused at export.

**Version 1 bundles still load:** the loader accepts `bundle_version` `"1"` and `"2"`; every field added in v2 (marked **v2** below) is null (or absent from step and finding objects, read as null) in a v1 bundle, and clients show "not recorded" for it.

## Fields
| Field | Type | Meaning |
|---|---|---|
| `bundle_version` | `"2"` (`"1"` still loads) | bumped on any breaking change |
| `episode` | str | episode id = folder name = session id |
| `plant` | str | `p1_grfics`, `p2_gasline` |
| `scenario`, `title`, `seed`, `batch` | str / int / str or null | from `meta.json`; `batch` names the sealed batch for scoring episodes (null for smoke/tuning) |
| `expected` | [str] | verdicts the scenario expects |
| `result` | {verdict, match, valid, problems} | from `verdict.json` (the runner's view, incl. pre/postflight validity) |
| `plan_hash`, `plan` | str, object | the confirmed plan exactly as logged at `session_start` |
| `confirmation` **v2** | {plan_hash, by, role, date, defaults?} or null | the person's confirmation record logged at `session_start` |
| `assumptions` **v2** | [str] or null | the plan's stated assumptions, e.g. "Positive isolation upstream assumed" |
| `plan_check_override` **v2** | str or null | the override text logged at `session_start` and stamped on every verdict |
| `plant_map` | object or null | the plant graph for the plant view (nodes, pipes, instruments); null if not supplied |
| `process_time_scale` | number | process seconds = wall seconds × scale |
| `steps` | [{k, kind, targets, required_state, marked_t, marked_by, verified_by, verified_t, reopened, result}] | plan steps with mark time (wall s, Docker VM clock) and result PASS / FAIL / UNKNOWN / null. **v2:** `marked_by`, `verified_by`, `verified_t` (names as entered, null until done) and `reopened` ([{by, t, reason}]) |
| `evaluations` | [{id, t, source, step, rules, findings, verdict_after, window}] | every logged evaluation (`step`, `monitor`, `plan`, `process`, `camera`) with its findings and the exact window the rules saw (replayable). Plan findings carry `path` (node list) for drawing open paths red. **v2:** each finding carries `id` = `<eval_id>:<rule_id>` (the finding id used by the API, explain citations and links); camera evaluations carry `point` |
| `verdicts` | [{t, verdict, source, track, reasons}] | verdict timeline; `track` is `data_only` or `with_camera` |
| `signals` | {t: [..], tag: [..]} | what ZeroState read, ≤ 1 Hz (from `signals.jsonl` when kept, else from the evaluation windows); the downsampled series the baselines use |
| `signals_sha256` **v2** | str or null | SHA-256 of the full local `signals.jsonl`: from `meta.json`, else the batch's `signals_sha256.json`, else hashed from the file (`--runs-dir` points at it, e.g. the bench worktree's `runs/`, read only); a file that does not match the recorded hash is refused at export; null when none is known |
| `camera` | [object] | logged camera readings (value, readable, frame `frame_sha256`, box, crop hash, feedback value, capture time); empty when the camera was off. Viewer label: **"idealised camera (renders the simulator's true state)"** |
| `truth` | {eval_only: true, t: [..], key: [..]} or null | simulator internals, ≤ 1 Hz, for scoring only. Viewer label: **"simulator internals — not read by ZeroState's data checks"** |
| `faults` | [object] | faults the runner injected, with their time |
| `audit` | {events, chain_head} | event count and the hash of the last audit row (ties the bundle to the chain) |

Names: `eval-operator`, `eval-verifier` and `eval-runner` are the benchmark runner's; viewers show them as **"test harness"**.

Times are wall seconds (epoch) on the Docker VM clock, the same clock as the audit log. Sizes measured on P1 smoke episodes (v1): ~35 KB each.
