# Bisset — Roadmap

Updated: 2026-06-08 (workflow phases deferred). Order = priority. Each item ships as its own
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

### 1. Hardening backlog (small, opportunistic)
- pytest adapter coverage (currently always 0; gate on coverage is
  behave-only and opt-in)
- storage lock semantics: `update_step`/`add_event` bypass `_require_lock`
  (pre-existing inconsistency flagged in review)
- uniform HTTP 400 validation for missing body fields (today: KeyError → 500,
  house style)
- atomic interview writes: `interview_question` issues two commits
  (question insert + status update); a crash between them leaves an orphan
  open question invisible to the gate (flagged in review, negligible
  single-user risk); `analysis_approve` has the analogous non-atomic
  materialization (declared, single-user risk)

## Later

### Workflow phases (deferred — candidate for removal)
The v2 design framed `new_project` / `new_feature` / `generate_tests` as
meta-phases (interview → design → generate → execute) that produce concrete
steps and then disappear. **This is now largely subsumed:** interview tools,
analysis tools, and the execute loop each already implement the "meta-step
that produces steps and disappears" pattern, and `workflow_type` is otherwise
a dead label. Building a phase state machine on top would mostly re-litigate
the conditional gates already shipped with interview and analysis (premature
abstraction over two working flows). The only residual gap is the greenfield
`design` phase of `new_project`, and even that is covered in practice by
`analysis_submit` (a reviewable pipeline proposal) — framing, not capability.

Decision: do not build now. Re-evaluate only if dogfooding (developing a
real feature *through* Bisset) surfaces a concrete moment where
`session_status` does not already tell the agent what to do next. Absent that
evidence, this item is likely to be dropped.

## Non-goals (for now)

UI, cloud/deployment, multi-agent orchestration, workflow packs.
