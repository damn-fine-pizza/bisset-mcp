# Bisset — Roadmap

Updated: 2026-06-07. Order = priority. Each item ships as its own
design → plan → reviewed implementation cycle (see `docs/plans/`).

## Delivered

- **v2 engine** — projects/sessions/steps, declarative rule engine, gates,
  test-runner adapters (behave/pytest/generic), SQLite registry, MCP exposure
- **BDD gate, proven** — sane default rules, gate-integrity fixes, real
  scenario coverage from behave; deterministic demo (`scripts/demo_bdd_gate.sh`)
  that fails if the gate fails to block; demo runs as a CI job on every push
- **Gherkin tools** — `step_set_feature` / `step_get_feature` /
  `step_validate_feature`: the agent hands Gherkin to Bisset; disk = truth,
  DB = SHA-256 registry; drift detected, reported, realigned, audited

## Next

### 1. `interview_answer` — interview as Bisset state
Today the requirements interview happens in chat (Claude asks, you answer)
and only its *outcome* reaches Bisset via `step_add`/`step_set_feature`. The
conversation itself is lost on session end.

Goal: the interview becomes Bisset state — questions and answers persisted,
resumable via `session_resume`, fully visible in `event_log`. Bisset acts as
secretary of the requirements phase, not just of execution. The existing
`bisset/interviewer` prompt drives the questions; Bisset stores the dialogue
and tracks completeness.

Scope sketch (to be designed): interview storage (per session), tool(s) to
record an answer and get the next open question, completion signal that
hands over to step generation. Bisset still calls no LLM.

## Later

### 2. `analyze_codebase`
For existing projects: Claude analyzes the codebase, Bisset persists the
proposed step list + draft features as reviewable pipeline state
(`generate_tests` / `new_feature` workflows depend on this).

### 3. Workflow phases
Make `new_project` / `new_feature` / `generate_tests` real meta-phases
(interview → design → generate → execute) that produce concrete steps and
then disappear, as per the v2 design.

### 4. Hardening backlog (small, opportunistic)
- pytest adapter coverage (currently always 0; gate on coverage is
  behave-only and opt-in)
- storage lock semantics: `update_step`/`add_event` bypass `_require_lock`
  (pre-existing inconsistency flagged in review)
- schema migration ladder: switch to a stepwise version loop before v3
- uniform HTTP 400 validation for missing body fields (today: KeyError → 500,
  house style)

## Non-goals (for now)

UI, cloud/deployment, multi-agent orchestration, workflow packs.
