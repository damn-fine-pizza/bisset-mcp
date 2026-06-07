# Bisset — Roadmap

Updated: 2026-06-07 (analysis tools delivered). Order = priority. Each item ships as its own
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
- **Interview as state** — `interview_question` / `interview_answer` /
  `interview_complete`: the requirements dialogue persisted per session,
  resumable mid-question, audited in `event_log`; conditional gate blocks
  `step_add` while an interview is open; stepwise migration ladder (schema v3)
- **Analysis as state** — `analysis_submit` / `analysis_view` /
  `analysis_approve` / `analysis_discard`: for existing projects, Claude's
  codebase analysis persisted as a reviewable pipeline proposal (step list +
  Gherkin drafts in DB); approval materializes real steps + feature files;
  conditional gate blocks `step_add` while a proposal is open (schema v4)

## Next

### 1. Workflow phases
Make `new_project` / `new_feature` / `generate_tests` real meta-phases
(interview → design → generate → execute) that produce concrete steps and
then disappear, as per the v2 design.

## Later

### 2. Hardening backlog (small, opportunistic)
- pytest adapter coverage (currently always 0; gate on coverage is
  behave-only and opt-in)
- storage lock semantics: `update_step`/`add_event` bypass `_require_lock`
  (pre-existing inconsistency flagged in review)
- uniform HTTP 400 validation for missing body fields (today: KeyError → 500,
  house style)
- atomic interview writes: `interview_question` issues two commits
  (question insert + status update); a crash between them leaves an orphan
  open question invisible to the gate (flagged in review, negligible
  single-user risk)

## Non-goals (for now)

UI, cloud/deployment, multi-agent orchestration, workflow packs.
