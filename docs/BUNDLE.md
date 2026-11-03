# Episode bundle (version 1)

The only thing the public replay viewer (Phase 3, `site/` on Vercel, static) reads. One file per episode: `bundle.json.gz` (gzipped JSON), written by `eval/tools/export_bundle.py` from a published episode (`eval/results/episodes/<episode>/` or `eval/results/bench/<batch>/<episode>/`). Schema in code: `Bundle` in `eval/tools/export_bundle.py` (pydantic, `extra="forbid"`); `tests/test_bundle.py` exports a real episode, loads it back and validates it.

Nothing live is hosted publicly: a bundle holds logged data only. No key, no API address, no frames (camera readings carry frame hashes). A bundle containing a key-like string is refused at export.

## Fields
| Field | Type | Meaning |
|---|---|---|
| `bundle_version` | `"1"` | bumped on any breaking change |
| `episode` | str | episode id = folder name = session id |
| `plant` | str | `p1_grfics`, `p2_gasline` |
| `scenario`, `title`, `seed`, `batch` | str / int / str or null | from `meta.json`; `batch` names the sealed batch for scoring episodes (null for smoke/tuning) |
| `expected` | [str] | verdicts the scenario expects |
| `result` | {verdict, match, valid, problems} | from `verdict.json` (the runner's view, incl. pre/postflight validity) |
| `plan_hash`, `plan` | str, object | the confirmed plan exactly as logged at `session_start` |
| `plant_map` | object or null | the plant graph for the plant view (nodes, pipes, instruments); null if not supplied |
| `process_time_scale` | number | process seconds = wall seconds × scale |
| `steps` | [{k, kind, targets, required_state, marked_t, result}] | plan steps with their mark time (wall s, Docker VM clock) and result PASS / FAIL / UNKNOWN / null |
| `evaluations` | [{id, t, source, step, rules, findings, verdict_after, window}] | every logged evaluation (`step`, `monitor`, `plan`, `process`, `camera`) with its findings and the exact window the rules saw (replayable). Plan findings carry `path` (node list) for drawing open paths red |
| `verdicts` | [{t, verdict, source, track, reasons}] | verdict timeline; `track` is `data_only` or `with_camera` |
| `signals` | {t: [..], tag: [..]} | what ZeroState read, ≤ 1 Hz (from `signals.jsonl` when kept, else from the evaluation windows) |
| `camera` | [object] | logged camera readings (value, readable, display, frame hash, capture time); empty when the camera was off |
| `truth` | {eval_only: true, t: [..], key: [..]} or null | simulator ground truth, ≤ 1 Hz — **eval only**: ZeroState never saw it; the viewer must label it as such |
| `faults` | [object] | faults the runner injected, with their time |
| `audit` | {events, chain_head} | event count and the hash of the last audit row (ties the bundle to the chain) |

Times are wall seconds (epoch) on the Docker VM clock, the same clock as the audit log. Sizes measured on P1 smoke episodes: ~35 KB each.
