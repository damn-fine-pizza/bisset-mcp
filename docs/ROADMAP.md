# Bisset — Roadmap

Updated: 2026-06-09 (workflow phases dropped after dogfooding). Order = priority. Each item ships as its own
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
- **Hardening** — missing required POST body fields return HTTP 400 (not 500);
  opening an interview question is atomic (row + `interview_status` in one
  transaction)
- **Non-behave gated artifact** — `step_set_test_path`: a pointer-only tool that
  registers an existing test file (e.g. a pytest module) as a step's run target,
  so non-behave projects engage the test/gate loop without Gherkin. Gate proven
  end-to-end (red blocks, green advances) against a real pytest subprocess

## Next

### 1. Hardening backlog (small, opportunistic)
- pytest adapter coverage (currently always 0; gate on coverage is
  behave-only and opt-in) — semantic choice, needs its own mini-design
- storage lock semantics: `update_step`/`add_event` and other writes bypass
  `_require_lock` (subtle; in-memory per-instance lock; do isolated)
- `analysis_approve` non-atomic materialization (writes N files to disk;
  declared single-user risk, not SQLite-transactionable)
## Dropped

### Workflow phases (was a roadmap item; removed 2026-06-09)
The v2 design framed `new_project` / `new_feature` / `generate_tests` as
meta-phases (interview → design → generate → execute) that produce concrete
steps and then disappear. This is **fully subsumed** by what shipped: interview
tools, analysis tools, and the execute loop each already implement the
"meta-step that produces steps and disappears" pattern, and `workflow_type` is
otherwise a dead label. A phase state machine on top would only re-litigate the
conditional gates already in interview and analysis.

Dropped on dogfooding evidence (2026-06-09): driving a real session, at every
point — empty session, after `analysis_submit`, after `analysis_approve` —
`session_status` (workflow_type + interview/analysis blocks + steps + the
`step_add` gate) already told the agent what to do next. No moment surfaced
where a phase layer would have added navigation the agent lacked. The only
residual gap (greenfield `design` for `new_project`) is covered in practice by
`analysis_submit`. Kept here as a record so the question is not re-opened.

## Non-goals (for now)

UI, cloud/deployment, multi-agent orchestration, workflow packs.
