# ZeroState HTTP API (contract, Phase 3)

Fixed in Phase 2, extended at the start of Phase 3 (P3-2) so the console (`ui/`, served by the API) and the replay site are UI work only. Rows marked **new in P3** or **changed in P3** are added by P3-2; everything else is what `src/zerostate/api/server.py` already serves. Implemented by `server.py` (FastAPI, started with `zs api`) in the `zs-api` container: same image as `zerostate`. Its network helper `zs-api-net` allows outbound traffic to the model proxy only — **the API never reaches a plant**.

## Security
- Published on **`127.0.0.1:8090` only** (the console can confirm and sign).
- The audit log is mounted **read-only** (`/audit`, SQLite `mode=ro`); the API **never writes `audit.sqlite`**. Human actions (mark, verify, reopen, sign, session start) go into the inbox (`/data/inbox.sqlite`) and the core session logs them. The inbox, drafts and confirmed plans (`/data`) are read-write for the API; it only reads saved camera frames (`/data/frames`).
- **Names are not authenticated** in this build: `by` is the name a person typed. Independence (PROC-INDEPENDENCE) means a different *entered* name.
- **Test-name guard (G10, new in P3):** `POST .../confirm` and `POST .../sign` with `by: "playwright-test"` are refused with **403** `{"error": "test_name_on_real_data"}` whenever the data dir is the real `/data`. That name is accepted only with a throwaway data dir (e.g. `/tmp/zs-ui-test`), for automated UI tests. Agents and scripts never confirm a plan or sign on real data.
- Status: Phase 2 = every Phase 2 endpoint exists and returns its schema (`tests/test_api_contract.py`). Phase 3 implements every row below and tests each against this contract.

Wording rule for every text field: PROJECT.md "never say" list, checked by `zerostate.wording`.

**Runner names:** clients show the names `eval-operator`, `eval-verifier` and `eval-runner` (the benchmark runner's) as **"test harness"**, never as a person. The API returns the logged name unchanged.

## Console
`GET /ui/` serves the console's static files (`ui/`; in the image `/app/ui`, `ZS_UI`) in live and replay mode; `GET /` redirects there. The console uses relative asset paths and calls the absolute `/api/...` routes below.

## Ids
- **Session id** = episode id = folder name (`[A-Za-z0-9_-]{1,64}`).
- **Evaluation id** (`eval_id`) = the audit-log row id of the `evaluation` event.
- **Finding id (new in P3)** = `<eval_id>:<rule_id>`, e.g. `412:LIVE-VALVE`. Stable: the same logged finding always has the same id, live and in replay. One evaluation runs each rule at most once, so the id is unique within a session. It appears in:
  - `GET /api/sessions/{id}` → `findings[].id` and `steps[].finding_ids`;
  - SSE `finding` events (`data.id`);
  - explain `cites`;
  - bundle v2 `evaluations[].findings[].id` (docs/BUNDLE.md);
  - console and site links: `#finding-<eval_id>:<rule_id>`.
  Draft plan-check findings (`POST /api/plans/import`, before any session) have no evaluation yet: `id` is null there.

`Finding` = `{id, rule_id, rule_version, status: PASS|FAIL|UNKNOWN, message, refs, path}`; `path` is the open path as a list of map node ids (drawn red).

## Plants and plans
| Method + path | Request | Response |
|---|---|---|
| `GET /api/plants/{plant}/map` | — | `PlantMap` (nodes, pipes, instruments, plan_defaults) for the plant view |
| `POST /api/plans/import` | multipart: `route` = `csv` \| `text` \| `image`, `plant`, and `file` (csv/image/pdf) or `text` | `Draft` |
| `GET /api/plans/drafts/{id}` | — | `Draft` |
| `PUT /api/plans/drafts/{id}` | `{list: IsolationList}` (edits from the table) | `Draft` (re-merged, re-checked) |
| `POST /api/plans/drafts/{id}/confirm` | `{by, role: "issuer"}` — a deliberate on-screen action by a named person | `{plan_hash, by, role, date}`; 409 while `unresolved` is not empty; 403 for `playwright-test` on real `/data` (new in P3) |

`Draft` = `{id, route, plant, list: IsolationList, transcript: str|null, plan_hash: str|null, findings: [Finding], unresolved: [str], defaults: [{field, value, source: "plant default"}]}`. `transcript` (photo route) is the model's verbatim reading of the sheet: the confirm screen shows the photo, the transcript and the table side by side. `defaults` lists values the person did not write that the plan takes from the plant (e.g. the fixed hold time); the confirm screen marks them as defaults and the confirmation record stores them.

Agents and scripts never call the confirm endpoint on real data (CLAUDE.md).

## Sessions
| Method + path | Request | Response |
|---|---|---|
| `GET /api/sessions` **new in P3** | — | `[SessionSummary]`, newest first |
| `POST /api/sessions` **new in P3** | `{plant, plan_hash, by, plan_check_override: str\|null}` | 202 `{queued: true, session}`; 404 if no confirmation record exists for `plan_hash`; 409 `{"error": "replay"}` in replay mode |
| `GET /api/sessions/{id}` **changed in P3** | — | `SessionDetail` |
| `GET /api/sessions/{id}/stream` **changed in P3** | — | Server-Sent Events (below) |
| `POST /api/sessions/{id}/steps/{k}/done` | `{by}` | `{queued: true}` (inbox) |
| `POST /api/sessions/{id}/steps/{k}/verify` | `{by}` (must differ from the name that marked it: PROC-INDEPENDENCE) | `{queued: true}` |
| `POST /api/sessions/{id}/steps/{k}/reopen` | `{by, reason}` (inch-and-test: PROC-RESET) | `{queued: true}` |
| `POST /api/sessions/{id}/sign` **changed in P3** | `{by, role, note, outcome: "accepted"\|"not_accepted"}` — on-screen action with name and role; **no voice route reaches it** | `{queued: true}`; 409 for `accepted` unless both tracks read `NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF`; 403 for `playwright-test` on real `/data` |

**Start (`POST /api/sessions`)** — live mode only. The API does not read the plant: it puts a `session_start` request in the inbox (session = a new id it returns) and the core runs it with `zs session start --session <id> --from-inbox` (started in the `zerostate` container by the operator or the demo driver; the API can't start it). The core refuses as it does from the command line: plan not confirmed by a person, plan hash mismatch, or a plan check that did not pass with no override text. A refused start is logged by the core as `session_refused {reason}` under the returned id, so `GET /api/sessions/{id}` shows `state: refused` and the reason; the API never fakes a session.

**Sign outcomes.** `accepted` is the console's "Accept and sign" (only offered on NO DISCREPANCY). `not_accepted` is "Close — not accepted" on BLOCKED or ESCALATED: a closing signature that records the job was not accepted; it never reads as approval. Only a signature closes a session. A missing `outcome` is `not_accepted`. The core applies the same rule (also to `zs sign --outcome`): an `accepted` it can't honour is logged as `sign_refused` (listed in `refused`) and the session stays open.

`SessionSummary` = `{id, plant, plan_hash, started: wall s, state, verdict, verdict_with_camera, signed: bool}`.

`SessionDetail` (P2 keys kept; `steps` changed from a map to a list):
```
{
  id, plant, state: warming_in|ready|closed|stopped|refused, started: wall s,
  plan_hash, plan: IsolationPlan,                       // as logged at session_start
  confirmation: {plan_hash, by, role, date, defaults?} | null,
  assumptions: [str],                                   // e.g. "Positive isolation upstream assumed"
  plan_check_override: str | null,                      // e.g. "control-valve isolation accepted for live-evidence testbed"
  steps: [Step],
  findings: [Finding & {eval_id, source, step, t}],     // every logged finding, in log order
  verdict: str | null,  verdict_with_camera: str | null,   // as before (data-only / with-camera)
  tracks: {
    data_only:   {verdict, reasons: [str], t, stamp} | null,
    with_camera: {verdict, reasons: [str], t, stamp, models} | null
  },
  stamp, refused: [..], camera_pending: int,            // as before
  signature: {by, role, note, outcome, verdict_at_signing, verdict_with_camera_at_signing, t} | null
}
Step = {k, kind, targets: [str], required_state: number|null,
        marked_by, marked_t, verified_by, verified_t,   // null until done; names as entered, times wall s
        reopened: [{by, t, reason}], result: PASS|FAIL|UNKNOWN|null, finding_ids: [str]}
```
Verdict values: `BLOCKED`, `ESCALATED`, `NO_DISCREPANCY_FOUND_AWAITING_SIGNOFF`, or null (evaluating). There is no other pass value. `assumptions` and `plan_check_override` come from `session_start` and are stamped into every verdict; the console shows them in a permanent strip.

### Stream events (`GET /api/sessions/{id}/stream`)
Tailed from the audit log and `signals.jsonl`; each event's `data` is the logged event `{id, ts, session, kind, payload}` unless noted. The stream ends after `signature` or `session_stopped`.

| `event:` | From | Notes |
|---|---|---|
| `session_start` **new in P3** | `session_start` | plan, plan hash, confirmation, assumptions, override |
| `step` | `step_done`, `step_refused` | as in P2 |
| `step_verify` **new in P3** | `step_verify` | `{k, by}` |
| `step_reopen` **new in P3** | `step_reopen` | `{k, by, reason, pending}` |
| `evaluation` | `evaluation` | every source: `plan`, `step`, `monitor`, `process`, `camera` |
| `finding` **changed in P3** | each finding of an evaluation | `data` = `Finding` with `id` and `eval_id` |
| `camera_reading` **new in P3** | `camera_reading` | one display read: value, readable, frame hash, box, feedback value |
| `verdict` **changed in P3** | `verdict` | `payload.track` = `data_only` (absent in the log = data only) or `with_camera` |
| `signature` **new in P3** | `signature` | ends the stream |
| `session_stopped` **new in P3** | `session_stopped` | ends the stream |
| `signals` | `signals.jsonl` | newest sample only, ≤ 1 Hz; `data` = `{t, tag: [value, raw, quality]}` |

## Camera (new in P3)
Label everywhere: **"idealised camera (renders the simulator's true state)"**.

| Method + path | Response |
|---|---|
| `GET /api/sessions/{id}/camera/{eval_id}` | `CameraEvidence` for one `source: camera` evaluation; 404 if `eval_id` is not one |
| `GET /api/sessions/{id}/frames/{frame_sha256}.jpg` | the saved frame, `image/jpeg`; 404 when not kept (always in replay mode) |
| `GET /api/sessions/{id}/camera/{eval_id}/crop/{i}.png` | reading `i`'s crop, cut from the saved frame with the logged box by the same code the reader used; 404 when the frame is not kept |

`CameraEvidence` = `{eval_id, step, point, tag, mode: required|advisory, label, models, finding: Finding, verdict_after, with_camera_after, feedback: [[t, value]], readings: [{t, value, readable, note, frame_sha256, box: [x1, y1, x2, y2]|null, crop_hash, feedback_at, frame_url|null, crop_url|null}]}`. `box` is the SAM 3.1 display box (pixels); `value` is Muse Spark's reading of the crop; `feedback_at` is the valve feedback value it was compared with.

**Frames (core change, P3-2):** the camera code saves each evaluated frame to `/data/frames/<session>/<frame_sha256>.jpg` (JPEG, about 50 KB), named by the frame hash it logs in `camera_reading`, and logs each reading's `box`. The audit log keeps hashes only; anyone holding the file can check it against the logged hash. Bundles never carry frames.

## Explain (Phase 3)
`POST /api/sessions/{id}/explain {question}` → `{answer, cites: [finding id]}`. Muse Spark answers **only** from that session's logged findings (with ids), summarised windows and the plan; it can't change anything (no write path from this endpoint). Every answer cites at least one finding id (`<eval_id>:<rule_id>`); the console renders each as a link to that finding. An uncited answer is retried once, then a fixed fallback is returned. A request to override, approve, sign or pass gets the fixed reply, with no model call: **"I can only explain the evidence; only code decides and only a person signs."** Needs the key, in replay mode too (503 without it).

## Voice (Phase 3, changed in P3)
`POST /api/voice/command`, body `{session}` plus **either** `{audio}` (base64 recording; transcribed by the chosen speech model — until P3-5 wires one, it returns `unknown` with a read-back saying so) **or** `{transcript, asr: "<model id>"}` (text already transcribed, with the id of the model that did it). `session` gives the plan the phrase is matched against (optional for P2 callers: without it only `status`/`repeat`/`confirm`/`cancel`/`unknown` can result).
→ `{transcript, asr, intent, k: int|null, read_back}`.

| `intent` | Meaning |
|---|---|
| `step_done` | the person said step `k` is done; `read_back` repeats the step's targets and state and asks for confirm |
| `confirm` | yes to the last read-back |
| `cancel` | no to the last read-back |
| `status` | read the current verdict tracks and the next step |
| `why` | read the reasons of the current verdict |
| `repeat` | repeat the last read-back |
| `unknown` | anything else; `read_back` asks a clarifying question |

**It never acts.** The voice route writes nothing (no inbox row). The console speaks `read_back`; a step is marked only when the person then confirms (by voice `confirm` or a click) and the console calls `POST .../steps/{k}/done`. A spoken valve phrase maps to step `k` only if it names **all** of that step's targets **and** its required state; otherwise the intent is `unknown` with a clarifying read-back (never a guess at a step). **`/sign`, verify and reopen are unreachable from voice**: there is no intent for them and the handler references no inbox, sign, verify or reopen code (tested).

## Replay mode (new in P3)
`zs api --replay <bundle_dir>` serves the recorded sessions in every `bundle.json.gz` under `<bundle_dir>` (v1 and v2; docs/BUNDLE.md) **read-only, lab-free, no key**:
- Same GET endpoints and shapes: `GET /api/sessions` lists the bundles (session id = episode), `GET /api/sessions/{id}` is built from the bundle, `GET /api/plants/{plant}/map` returns the bundle's `plant_map`, the camera endpoint returns readings with `frame_url`/`crop_url` null.
- The stream sends the recorded events in order, then ends; `?speed=N` paces them at N × recorded time.
- **Every write returns 409 `{"error": "replay", "detail": ...}`**: import, draft edit, confirm, session start, done, verify, reopen, sign; voice too (there is no live step to mark). Explain is the only POST served.
- Explain works only with the key (503 without it); nothing else needs one.
- It is the README's main "run it" path, the Playwright fixture and the explain-check harness.

## Errors
JSON `{error, detail}` with 400 (bad input), 403 (`test_name_on_real_data`), 404 (unknown id), 409 (draft not confirmable / session state / `replay`), 503 (model unavailable or over budget: the API keeps working without model features).
