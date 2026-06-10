# Design — Gated artifact for non-behave projects (`step_set_test_path`)

Date: 2026-06-10
Status: design approved, plan pending
Backlog item: "gated artifact is behave-shaped" (ROADMAP "Next" §1)

## Problem

A pipeline step engages the test/gate loop only if it has a `feature_path`.
Today the only sanctioned way to set it, `step_set_feature`, validates Gherkin
via `check_syntax` and writes the file under `features_dir`. A pytest-tested
change (Bisset's own domain) has no Gherkin to hand over, so its real step ends
up with `feature_path=None`:

- `run_tests` returns `(0, 0)` immediately (engine.py:561) → `no_tests`
- under the default rules `no_tests → ask_user`

The test/gate loop never engages. Surfaced by dogfooding (2026-06-09). The only
current workaround is a raw `step_edit` of `feature_path` to the test file —
which is incoherent (see §4).

## Scope

**Execute loop only.** A new pointer-only tool lets a real step carry a
non-Gherkin test artifact. The analysis flow (`analysis_submit` /
`analysis_approve`) stays Gherkin-only; carrying a non-Gherkin pointer through
analysis (where the pointer would target a file Claude has not yet written at
approve time) is deferred as a separate backlog follow-up.

## Pinned decisions

1. **Pointer-only role.** Bisset stays agnostic about non-Gherkin test content.
   Claude writes the test file to disk (TDD red phase); a new tool registers the
   path. Bisset never writes or parses Python test source.
2. **Bare pointer.** The tool stores only `feature_path`; `feature_content` and
   `feature_hash` stay `None`. `run_tests` always reads disk, so it runs
   correctly; no spurious drift events on test code Claude edits as part of the
   loop.
3. **New tool, not blessing `step_edit`** (see §4).
4. **Existence check is mandatory** — registration rejects a path whose file
   does not exist under the project root.

## Success criterion (end-to-end)

Mirror `demo_bdd_gate.sh` ("fails if the gate fails to block"): for a pytest
step pointed via the new tool, a **red** test blocks (`step_complete` →
retry/ask_user, never advance) and a **green** test advances. Unit-testing the
tool is not enough; the plan must prove the gate closes on the exact case this
feature is built for.

## The tool: `step_set_test_path`

Signature: `step_set_test_path(step_id, session_id, path)`.

Engine method `set_test_path(step_id, session_id, path)`:

1. Resolve step / session / project — same error shape as `set_feature`
   (`ValueError` on missing step/session/project).
2. **Path safety** — a new validator, NOT `sanitize_filename` (which forbids
   `/` and is features-dir specific; here we need subdirectories like
   `tests/test_foo.py`):
   - reject absolute paths;
   - `os.path.normpath` the input;
   - reject if it escapes the project root (normalized path starts with `..`
     or, after joining with the project path, resolves outside it).
3. **Existence** — the file must exist under the project root, else a clear
   `ValueError`. (This is UX, not a safety guard: `run_tests` already catches
   `FileNotFoundError` → `failed=1`. But file-first ordering makes the check
   natural and the message better, and it matches TDD: the red test exists
   before it is pointed at.)
4. Write **only** `feature_path` (normalized, project-relative) and **clear**
   `feature_content=None`, `feature_hash=None` (no stale Gherkin, no spurious
   drift).
5. Emit a `test_path_set` audit event (`step_edit` emits none).
6. **Adapter-agnostic** — no gate on the adapter. Typical for pytest/generic; a
   behave project keeps using `step_set_feature`.

Return: `{"feature_path": <rel>, "set": true}`.

## Why a new tool, not `step_edit` (§4)

`step_edit` (app.py:559) is a raw passthrough to `update_step(**body)`. It
already accepts `feature_path` — that is the current workaround — but as a
primary path it is wrong:

- no path safety (accepts absolute paths / traversal);
- no existence check;
- emits no audit event (`step_edit` never calls `add_event`);
- leaves `feature_content`/`feature_hash` stale: if the step previously had a
  Gherkin feature, the old hash survives and `run_tests` (engine.py:569) fires a
  spurious `feature_drift`, realigning `feature_content` to the pytest source.

`step_edit` stays as the generic escape hatch. `step_set_test_path` is the
**only sanctioned path** to give a non-Gherkin step a `feature_path`, with the
affordance and description that tell Claude this is how a pytest step is gated.

## Integration — no changes needed

- `run_tests`: already runs `[runner] + test_args + [feature_path]`
  (engine.py:573-576); with `feature_hash=None` it skips drift (engine.py:569).
- `get_feature`: reads disk, returns the pytest file content,
  `feature_drifted=False` (hash `None`). Harmless.
- `step_validate_feature`: already raises if adapter != behave (engine.py:496).
- `step_complete` / rule engine: unchanged — they read recorded `test_runs`.

## Wiring

- `app.py`: `@app.post("/step_set_test_path")`, with the missing-field → HTTP
  400 pattern (like `step_set_feature`).
- `mcp_server/server.py`: tool entry next to `step_set_feature`; **not** in
  `client.py`'s `_GET_TOOLS` (it is a POST).
- **No schema change** — reuses the `feature_path` column. `SCHEMA_VERSION`
  stays 4; no migration rung.

## Out of scope (noted, not addressed)

- The `generic` adapter appends `feature_path` to an arbitrary command, so a
  command like `make test` would receive a stray path argument. Pre-existing;
  not addressed here.
- After merge, the MCP proxy must be reconnected to expose the new tool (the
  HTTP backend hot-reloads).
