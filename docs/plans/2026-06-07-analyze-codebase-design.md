# Analyze Codebase — Design Document

**Date:** 2026-06-07
**Status:** Implemented
**Scope:** Roadmap item 1 — `analyze_codebase`: for existing projects, Claude
analyzes the codebase and Bisset persists the proposed step list + draft
features as reviewable pipeline state (`analysis_submit`, `analysis_view`,
`analysis_approve`, `analysis_discard`).

## Objective

Today Bisset can guide a project from scratch (interview → steps → BDD gate),
but there is no structured entry path for an *existing* codebase: the analysis
happens in chat and its outcome reaches Bisset only as hand-rolled `step_add`
calls. The `generate_tests` / `new_feature` workflows depend on this missing
piece.

Goal: the analysis outcome becomes Bisset state — a **pipeline proposal**
(step list + Gherkin drafts) persisted per session, freely revisable, audited
in `event_log`, with an explicit approval that materializes it into real steps
and feature files. Claude does the thinking (driven by the `bisset/analyzer`
prompt); Bisset records and gates. Bisset still calls no LLM.

Out of scope (deferred): workflow phases, making the analysis *mandatory* for
any workflow type, behave step-definition generation.

## Decisions

1. **Editable draft + block approval.** The proposal lives as a per-session
   draft that Claude (on human direction) can revise freely; a single explicit
   approval materializes it into real steps. Mirrors the interview model:
   opened → worked → explicitly closed.
2. **Revision = full re-submit.** `analysis_submit` on an `open` proposal
   replaces the whole step list and logs `analysis_revised`. No granular
   per-proposal-step edit tools: Claude holds the full proposal in context and
   re-submits it; the audit trail keeps the fact that a revision happened.
3. **Gherkin drafts live in the DB.** Each proposed step may carry a
   `feature_draft`; it is part of the proposal state. Only on approval is it
   materialized to disk through the existing `set_feature` flow (disk = truth
   applies to real steps, not to drafts). No orphan files if the proposal is
   discarded.
4. **Conditional gate, interview-style.** An `open` proposal blocks manual
   `step_add` with a structured, actionable error ("approve or discard the
   proposal"). Sessions that never start an analysis behave exactly as today —
   demo, CI, and quick prototyping flows are untouched. The invariant is "if
   you open a proposal, you close it", not "you must analyze".
5. **Proposals are reopenable.** `analysis_submit` on an `approved` /
   `discarded` proposal opens a fresh one and re-arms the gate.
6. **Validate Gherkin at submit time.** Every `feature_draft` goes through
   `check_syntax` on submit, with per-step structured errors and nothing
   written on failure. Failing early means approval can never fail on syntax.

## Data model (schema v4)

New ladder rung `_migrate_v3_to_v4` + bump `SCHEMA_VERSION = 4` (stepwise
ladder, foreign-lineage sentinel fires for every populated version). Additive:

- `ALTER TABLE sessions ADD COLUMN analysis_status TEXT` — `NULL` (never
  started) / `'open'` / `'approved'` / `'discarded'`. Lives on the session row
  like `interview_status`: the gate check in `add_step` already holds that
  row, zero extra queries.
- New table:

  ```sql
  CREATE TABLE proposal_steps (
      id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL REFERENCES sessions(id),
      "order" INTEGER NOT NULL,
      title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      feature_draft TEXT,          -- Gherkin draft; NULL = no draft
      created_at REAL NOT NULL
  );
  ```

`proposal_steps` always holds **the current proposal** (re-submit deletes and
re-inserts the session's rows); revision history lives in `event_log`.

## Tools

All exposed at both layers following the existing flat pattern: FastAPI
endpoint `/{tool_name}` + MCP tool with matching schema.

| Tool | Type | Contract |
|------|------|----------|
| `analysis_submit(session_id, steps[])` | write | `steps` = list of `{title, description?, feature_draft?}`. Empty list or empty title → structured error, nothing written. Every `feature_draft` validated with `check_syntax` (per-step errors). On `NULL` status → open the proposal, log `analysis_submitted`. On `'open'` → replace, log `analysis_revised`. On `'approved'` / `'discarded'` → fresh proposal, re-arm the gate, log `analysis_submitted` with `previous_status` in the event data. |
| `analysis_view(session_id)` | read | Status + proposed steps with drafts. Never started → explicit response, not an error. |
| `analysis_approve(session_id)` | write | Invariants: `analysis_status == 'open'` **and** `interview_status != 'open'` (open interview → structured error: "complete the interview first"). Materializes in order: for each proposed step → real step at `order = max + 1` (direct storage write — the gate guards the manual tool path, not the internal promotion), then if `feature_draft` is present → existing `set_feature` flow (disk write, SHA-256 registered, `feature_set` event; path derived from `features_dir` + title, the proposal carries no path). Then `analysis_status = 'approved'`, log `analysis_approved` with counts. Responds with the proposal → real step id mapping. |
| `analysis_discard(session_id)` | write | Only on `'open'` → `'discarded'`, log `analysis_discarded`. Rows remain readable via `analysis_view`. |

## Gate — two imperative gates in `add_step`

Both gates coexist, **fixed check order: interview first, then analysis**,
each with its own actionable error:

- `interview_status == 'open'` → error carrying the pending question
  (existing, unchanged)
- `analysis_status == 'open'` → error: "an open analysis proposal with N
  steps exists — approve it (`analysis_approve`) or discard it
  (`analysis_discard`)"

Both may be open simultaneously (the agent may interview *and* analyze);
`NULL` and terminal states behave exactly as today.

Like the interview gate, this is deliberately *not* a rule-engine rule: it
guards an internal consistency invariant of the proposal itself and needs no
configuration.

## Approval — declared transaction boundary

Approval is N × (step row + Gherkin written to disk + SHA registered):
**non-atomic**, like the interview's two-commit write already flagged in the
hardening backlog. The ordering is chosen so a partial failure leaves a
consistent prefix (real steps with features already written; proposal still
`open`). Accepted single-user risk, documented here on purpose — a fix
belongs to the hardening backlog, not to this work.

## Resume and visibility

`session_status` and `session_resume` responses gain an `analysis` block
(`null` when never started):

```json
{
  "status": "open",
  "steps_proposed": 5,
  "features_drafted": 3,
  "steps": [{"order": 1, "title": "...", "has_draft": true}]
}
```

On resume, the agent knows a pending proposal exists and what it contains.

## Events

`analysis_submitted`, `analysis_revised`, `analysis_approved`,
`analysis_discarded` — naming style consistent with the existing
`feature_set` / `interview_completed`.

## Prompt: `bisset/analyzer`

Rewritten (as the interviewer prompt was for the interview tools): instructs
Claude to deliver the analysis outcome via `analysis_submit`, wait for human
review, re-submit on feedback, and call `analysis_approve` only on explicit
human confirmation.

## Error handling

- Empty `steps` list / empty `title` → structured error, nothing written.
- Invalid Gherkin in any `feature_draft` → per-step structured errors,
  nothing written.
- `analysis_approve` / `analysis_discard` with no open proposal → error
  naming the actual status.
- `analysis_approve` with an open interview → error pointing at
  `interview_complete`.
- Every error is actionable: it tells the agent the correct next call.

## Testing

TDD, same style as the interview work (starting from 132 green):

- **storage**: migration ladder (fresh→v4, v1→v4, v2→v4, v3→v4, idempotence,
  foreign-lineage sentinel fires for every populated version),
  `proposal_steps` CRUD, `analysis_status` transitions
- **engine**: submit/revise/approve/discard happy paths, Gherkin validation
  at submit, gate on `add_step` across the four states, double-gate check
  order, approve blocked by an open interview, materialization (real steps +
  feature files on disk + id mapping), `analysis` block in status/resume
- **app**: endpoint contracts for the four tools
- **e2e**: submit → `step_add` blocked → approve → real steps + feature files
  on disk → `step_add` ok → resume reports the pending proposal
