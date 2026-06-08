# Hardening Batch — Design Document

**Date:** 2026-06-08
**Status:** Approved
**Scope:** Two items from the roadmap hardening backlog: uniform HTTP 400 on
missing body fields (#3) and atomic interview-question open (#4). Deferred this
round (user decision): pytest-adapter coverage (#1, a semantic choice, not a
bug) and storage lock semantics (#2, subtle/high-risk, to be done isolated).

## Item 3 — HTTP 400 on missing required body fields

**Today:** POST handlers read `body["x"]`; a missing field raises `KeyError`,
caught by the broad `except Exception` and returned as HTTP 500
(`is_error: True`, status 500). A client omitting a field gets a server-error
shape for what is a client mistake.

**Change:** in each POST handler, catch `KeyError` **only around the field
extraction**, return a 400 with an actionable message, and leave the broad
`except Exception → 500` below as the fallback. Scoping the catch to the
extraction is the whole point: a deeper `KeyError` (e.g. a raw `step["title"]`
in storage) must still fall through to 500, not be mislabelled "missing field".

```python
    try:
        body = await request.json()
        session_id = body["session_id"]
        steps = body["steps"]
    except KeyError as e:
        return ResponseWrapper.error(f"Missing required field: {e}", "XXX_ERROR", 400)
    try:
        result = request.app.state.engine.analysis_submit(session_id, steps)
        ...
    except Exception as e:
        return ResponseWrapper.error(str(e), "XXX_ERROR", 500)
```

Per-endpoint error codes and the timing/wrapper boilerplate stay as they are.
GET handlers are untouched: FastAPI already validates missing query params
(422) via the typed signature.

Applies to every POST handler that reads required body fields. Optional fields
(`body.get(...)`) are unaffected.

## Item 4 — Atomic interview-question open

**Today:** `engine.interview_question` issues two separate commits — insert the
question row (`add_interview_question`), then `set_interview_status('open')`. A
crash between them leaves an orphan open question the gate cannot see (the
session's `interview_status` is still NULL/complete).

**Change:** a single storage method that inserts the question **and** sets
`interview_status='open'` in one transaction (one commit). `engine.interview_question`
routes through it exclusively — the two-call path is removed, not left as a
second way to open an interview.

```python
    def add_interview_question(self, session_id: str, question: str) -> str:
        """Insert an open question AND set interview_status='open' atomically."""
        self._require_lock()
        qid = self._new_id()
        row = self.conn.execute(
            'SELECT COALESCE(MAX("order"), 0) + 1 FROM interview_questions '
            "WHERE session_id=?", (session_id,)).fetchone()
        self.conn.execute(
            'INSERT INTO interview_questions (id, session_id, "order", question, '
            "status, asked_at) VALUES (?,?,?,?,?,?)",
            (qid, session_id, row[0], question, "open", time.time()))
        self.conn.execute(
            "UPDATE sessions SET interview_status='open' WHERE id=?", (session_id,))
        self.conn.commit()
        return qid
```

`engine.interview_question` drops its now-redundant `set_interview_status('open')`
call. The reopened-detection (reading status before) and the audit events
(`interview_reopened`, `question_asked`) stay as they are: events are
best-effort by the interview design (a post-commit crash losing only an audit
event is the accepted degradation); the row+status invariant is what becomes
atomic.

**Out of scope:** `analysis_approve`'s analogous non-atomicity — it writes
files to disk per step, which SQLite transactions cannot span. It stays a
declared single-user risk in the roadmap.

## Testing

TDD, base 165 green.

- **#3 (app):** for representative POST endpoints, post a body missing a
  required field, assert `is_error is True` **and** `metadata.status == 400`
  (not 500). Cover at least one previously-500 endpoint per family
  (session/step/interview/analysis). A valid request still succeeds.
- **#4 (storage):** assert `add_interview_question` sets both the row and
  `interview_status='open'` in one call, and — the red-first lever — that it
  calls `conn.commit` **exactly once** (the old two-commit path committed
  twice; the both-writes-landed assertion alone passes against old code too,
  so the commit-count test is what pins the single-transaction property).
- **#4 (engine):** existing interview tests must stay green; `interview_question`
  still opens the interview and the gate still fires.

## Notes

Both items are behaviour-preserving for valid inputs: #3 only re-labels an
error class (500→400) for malformed requests; #4 changes only crash-safety,
invisible to a single-threaded happy path. No schema change, no migration.
