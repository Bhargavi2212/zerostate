# ZeroState — rules for coding agents (Claude Code + Ponytail)

Read first: docs/PROJECT.md (what + never-say list), docs/ARCHITECTURE.md, docs/STRUCTURE.md (where every file goes), docs/CLAIMS.md, and the current phase spec in docs/specs/.

## Workflow (every phase)
1. Read the phase spec. Plan in plan mode; list files you'll touch. Don't create files not in STRUCTURE.md without updating it in the same commit.
2. Ponytail on (`/ponytail full`). Climb the ladder: need it? → already here? → stdlib? → installed dep? → one line? → minimum + test.
3. Work item by item (P0-1, P0-2 …). For each: code → tests → `pytest` green → commit. **One commit per spec item or smaller. Never commit failing tests.**
4. Commit message: `P<phase>-<item> <what> (<claim ids>)`, e.g. `P0-3 read-only Modbus adapter (C1)`.
5. End of phase: `/ponytail-review branch`, fix findings, run the gate commands in the spec, paste gate output into docs/specs/PHASE_<n>_GATE.md, merge, tag `phase-<n>`.

## Environment
- Windows + PowerShell. `python -m venv .venv` then `.venv\Scripts\Activate.ps1`; `pip install -e .[dev]`. Never install into base/conda.
- Containers have their own pinned deps (deploy/Dockerfile).
- Secrets: `MODEL_API_KEY` only from environment. Never print, log or commit it. `.env` is gitignored; pre-commit runs a secret scan.

## Never cut (Ponytail "lazy, not negligent" — extended for this project)
These are trust boundaries. Minimum code is fine; skipping them or their tests is not.
- No write path to any plant from `src/zerostate` (adapters expose read/subscribe/history only).
- `src/zerostate` never imports `plants/` or `eval/`, never references truth endpoints (`/data/index.php`, port 55555).
- Bad / stale / placeholder / missing data → UNKNOWN → can never yield a pass.
- Verdict enum has no SAFE; the model may add a block, never remove one; only a human signature closes.
- Audit log is append-only and hash-chained.
- Every rule exports RULE_ID + RULE_VERSION and has one passing and one failing test.
- Every test named in docs/CLAIMS.md must exist.

## Don't
- Don't add dependencies not listed in the spec without saying why in the commit.
- Don't touch Fortiphyd files; GRFICS changes only in plants/p1_grfics/patch/.
- Don't write README numbers by hand — they come from eval output only.
- Don't use words from the PROJECT.md never-say list in code comments, UI text or docs.
