# Interview Tools — Design Document

**Date:** 2026-06-07
**Status:** Implemented
**Scope:** Roadmap item 1 — `interview_answer`: the requirements interview as
Bisset state (`interview_question`, `interview_answer`, `interview_complete`).

## Objective

Today the requirements interview happens in chat (Claude asks, the human
answers) and only its *outcome* reaches Bisset via `step_add` /
`step_set_feature`. The conversation itself is lost on session end.

Goal: the interview becomes Bisset state — questions and answers persisted in
the DB, resumable via `session_resume`, fully visible in `event_log`, with an
explicit hand-over to step generation. Claude does the thinking (driven by the
existing `bisset/interviewer` prompt); Bisset records and gates. Bisset still
calls no LLM.

Out of scope (deferred): `analyze_codebase`, workflow phases, making the
interview *mandatory* for any workflow type (see Gate below).

## Decisions

1. **Open question + answer, two moments.** A question exists as persisted
   `open` state from the moment Claude poses it; the answer closes it. This is
   what makes the interview resumable mid-question: `session_resume` can say
   "this question is pending — re-ask it".
2. **One open question at a time.** Matches the interviewer prompt ("ask one
   question at a time") and keeps resume semantics unambiguous (*the* pending
   question). Registering a second question while one is open is a structured
   error that reports the pending one.
3. **Claude declares completion; Bisset gates.** An explicit
   `interview_complete` call, validated against invariants (no open question,
   at least one answer). From the moment an interview is started, `step_add`
   is rejected until the interview is complete.
4. **Gate is conditional on existence.** Sessions that never start an
   interview behave exactly as today — demo, CI, and quick prototyping flows
   are untouched. The invariant is "if you start the interview, you finish
   it", not "you must interview". Promoting this to a declarative rule can
   happen later, with workflow phases.
5. **Answers are revisable, with audit.** Re-answering an answered question
   overwrites the answer and logs `answer_revised` (the human may correct
   themselves; the audit trail keeps the fact that a revision happened).
   Revising never changes `interview_status`: a revision on a `complete`
   interview leaves it complete — only `interview_question` reopens.
6. **Interviews are reopenable.** `interview_question` on a `complete`
   interview reopens it (`interview_reopened` event) and re-arms the gate:
   if you reopen it, you close it again.

## Data model (schema v3)

**Prerequisite — migration ladder.** `_migrate` currently early-returns for
any DB already at `SCHEMA_VERSION`, so new tables/columns would never reach
existing DBs; the roadmap flags "switch to a stepwise version loop before v3".
This ships as Task 1: a `MIGRATIONS` map of stepwise upgrade functions applied
in a loop while `current < SCHEMA_VERSION`, preserving the foreign-lineage
sentinel check. The v1→v2 path becomes the first ladder entry.

Then v3, additive:

- `ALTER TABLE sessions ADD COLUMN interview_status TEXT` — `NULL` (never
  started) / `'open'` / `'complete'`. Lives on the session row because the
  gate check in `add_step` already holds that row: zero extra queries, and
  the roadmap frames the interview as per-session state.
- New table `interview_questions`:

  ```sql
  CREATE TABLE interview_questions (
      id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL REFERENCES sessions(id),
      "order" INTEGER NOT NULL,
      question TEXT NOT NULL,
      answer TEXT,                -- NULL while open
      status TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'answered'
      asked_at REAL NOT NULL,
      answered_at REAL
  );
  ```

## Tools

All exposed at both layers following the existing flat pattern: FastAPI
endpoint `/{tool_name}` + MCP tool with matching schema.

| Tool | Type | Contract |
|------|------|----------|
| `interview_question(session_id, question)` | write | Register the question with `order = max + 1`, set session `interview_status = 'open'`. If a question is already open: structured error carrying the pending question. On a `complete` interview: reopen (log `interview_reopened`). Log `question_asked`. |
| `interview_answer(question_id, answer)` | write | Close the question (`status = 'answered'`, `answered_at`). On an already-answered question: overwrite, log `answer_revised` instead of `answer_recorded`. |
| `interview_complete(session_id)` | write | Invariants: no open question, ≥ 1 recorded answer. On success: `interview_status = 'complete'`, log `interview_completed`, respond with counts summary. On failure: structured error naming the pending question or the missing answers. |

## Gate

Imperative check in `engine.add_step`: if the session's
`interview_status == 'open'`, reject with a structured, actionable error in
the gherkin-tools style — it carries the pending question's text and tells the
agent what to do next ("answer it and call `interview_complete`"). `NULL` and
`'complete'` behave exactly as today.

This is deliberately *not* a rule-engine rule: the red-test gate guards step
acceptance and is configurable per session; this guards an internal
consistency invariant of the interview itself and needs no configuration.

## Resume and visibility

`session_status` and `session_resume` responses gain an `interview` block
(`null` when never started):

```json
{
  "status": "open",
  "asked": 5,
  "answered": 4,
  "pending_question": {"id": "...", "order": 5, "question": "..."}
}
```

`pending_question` is `null` when nothing is open. On resume, the agent knows
exactly where to pick up the thread — this is the headline requirement.

## Events

`question_asked`, `answer_recorded`, `answer_revised`,
`interview_completed`, `interview_reopened` — all in `event_log`, naming
style consistent with the existing `feature_set` / `feature_drift` /
`session_resumed`.

## Error handling

- Empty `question` / `answer` → structured error, nothing written.
- `interview_answer` on an unknown `question_id` → not found.
- `interview_question` with one already open → error carrying the open
  question.
- `interview_complete` never started, or with an open question, or with zero
  answers → error naming the precise cause.
- Every error is actionable: it tells the agent the correct next call.

## Testing

TDD, same style as the gherkin-tools work:

- **storage**: migration ladder (fresh→v3, v1→v3, v2→v3, idempotence,
  foreign-lineage sentinel preserved), interview_questions CRUD,
  `interview_status` transitions
- **engine**: question/answer/complete happy path, single-open-question
  invariant, revision, reopening, gate on `add_step` across the three states,
  interview block in status/resume
- **app**: endpoint contracts for the three tools
- **e2e**: interview → `step_add` blocked → complete → `step_add` ok →
  resume reports the pending question
