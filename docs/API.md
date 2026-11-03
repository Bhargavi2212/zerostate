# ZeroState HTTP API (contract, Phase 2)

Fixed in Phase 2 so the Phase 3 console (`ui/`, served by the API) is UI work only. Implemented by `src/zerostate/api/server.py` (FastAPI, started with `zs api`) in the `zs-api` container: same image as `zerostate`, port 8090 bound to **127.0.0.1 only** (the console can sign). Its network helper `zs-api-net` allows outbound traffic to the model proxy only — **the API never reaches a plant**.

Data access: the audit log is mounted **read-only** (`/audit`, SQLite `mode=ro`); the inbox, drafts and confirmed plans (`/data`) are read-write. The API never writes the audit log: human actions go into the inbox and the core session logs them. Status: Phase 2 = every endpoint exists and returns its schema (`tests/test_api_contract.py`); explain and voice are stubs until Phase 3.

Wording rule for every text field: PROJECT.md "never say" list (no "safe", no "verified isolation").

## Plants and plans
| Method + path | Request | Response |
|---|---|---|
| `GET /api/plants/{plant}/map` | — | `PlantMap` (nodes, pipes, instruments, plan_defaults) for the plant view |
| `POST /api/plans/import` | multipart: `route` = `csv` \| `text` \| `image`, `plant`, and `file` (csv/image/pdf) or `text` | `Draft` |
| `GET /api/plans/drafts/{id}` | — | `Draft` |
| `PUT /api/plans/drafts/{id}` | `{list: IsolationList}` (edits from the table) | `Draft` (re-merged, re-checked) |
| `POST /api/plans/drafts/{id}/confirm` | `{by, role: "issuer"}` — a deliberate on-screen action by a named person | `{plan_hash, by, role, date}`; 409 while `unresolved` is not empty |

`Draft` = `{id, route, plant, list: IsolationList, transcript: str|null, plan_hash: str|null, findings: [Finding], unresolved: [str], defaults: [{field, value, source: "plant default"}]}`. `transcript` (photo route) is the model's verbatim reading of the sheet: the confirm screen shows the photo, the transcript and the table side by side. `defaults` lists values the person did not write that the plan takes from the plant (e.g. the fixed hold time); the confirm screen marks them as defaults and the confirmation record stores them. `Finding` = `{rule_id, rule_version, status: PASS|FAIL|UNKNOWN, message, refs, path}`; `path` is the open path as a list of map node ids (drawn red).

Agents and scripts never call the confirm endpoint (CLAUDE.md).

## Sessions
| Method + path | Request | Response |
|---|---|---|
| `GET /api/sessions/{id}` | — | `{state, steps: {k: pending\|PASS\|FAIL\|UNKNOWN}, verdict, verdict_with_camera, stamp, refused, camera_pending}` (same as `zs status --json`) |
| `GET /api/sessions/{id}/stream` | — | Server-Sent Events: `evaluation`, `finding`, `verdict`, `step`, `signals` (≤ 1 Hz), tailed from the audit log and `signals.jsonl` |
| `POST /api/sessions/{id}/steps/{k}/done` | `{by}` | `{queued: true}` (inbox) |
| `POST /api/sessions/{id}/steps/{k}/verify` | `{by}` (must differ from the person who marked it: PROC-INDEPENDENCE) | `{queued: true}` |
| `POST /api/sessions/{id}/steps/{k}/reopen` | `{by, reason}` (inch-and-test: PROC-RESET) | `{queued: true}` |
| `POST /api/sessions/{id}/sign` | `{by, role, note}` — on-screen action with name and role; **no voice route reaches it** | `{queued: true}` |

## Explain (Phase 3)
`POST /api/sessions/{id}/explain {question}` → `{answer, cites: [evaluation ids / finding ids]}`. Muse Spark answers **only** from that session's logged findings and windows; it can't change anything (no write path from this endpoint). Phase 2: stub returning the schema.

## Voice (Phase 3)
`POST /api/voice/command {audio}` → `{transcript, intent: step_done|status|why|repeat|unknown, k: int|null, read_back}`. It does **not** act: the console speaks `read_back` and calls `/steps/{k}/done` only after the person confirms. It can never reach `/sign`. Transcription per the P2-5 result (Muse Voice Transcribe, or the browser's speech recognition labelled as such). Phase 2: stub returning the schema.

## Errors
JSON `{error, detail}` with 400 (bad input), 404 (unknown id), 409 (draft not confirmable / session state), 503 (model unavailable or over budget: the API keeps working without model features).
