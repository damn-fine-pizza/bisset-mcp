# Hardening Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two roadmap hardening fixes — return HTTP 400 (not 500) when a POST body omits a required field (#3), and make opening an interview question atomic (insert row + set `interview_status='open'` in one transaction) (#4).

**Architecture:** #3 — in each POST handler, a `KeyError` catch scoped to the field extraction maps missing fields to 400; the existing broad `except Exception → 500` stays below so deeper KeyErrors are unaffected. #4 — fold the status update into the existing `Storage.add_interview_question` (one commit), and drop the now-redundant second call in `engine.interview_question`.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, pytest.

**Conventions (binding):**
- Run all tests with `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q` from the repo root.
- Branch: `dev/feature0015-hardening` (already created, design doc committed).
- Baseline before Task 1: **165 passed**. Per-task expected counts are a guide; the running count is the truth — carry any constant offset forward.
- NEVER add Co-Authored-By or AI-attribution trailers to commits or PR bodies.
- Subagents MUST NOT run `git checkout` / `git switch`.

---

### Task 1: HTTP 400 on missing required body fields

Every POST handler that reads a required field via `body["x"]` (or
`body.pop("x")`) currently lets a missing field raise `KeyError`, which the
broad `except Exception` returns as HTTP 500. This task adds a `KeyError`
catch **scoped to the extraction** that returns 400 instead.

**The canonical transformation** (apply to every handler in the table below).
Wrap **only the required-field extraction** in a nested `try` catching
`KeyError`; the outer `try/except Exception → 500` is unchanged.

Before:
```python
@app.post("/x")
async def x(request: Request) -> Dict[str, Any]:
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.x(body["a"], body["b"])
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "X_ERROR", 500)
```

After:
```python
@app.post("/x")
async def x(request: Request) -> Dict[str, Any]:
    start = time.time()
    try:
        body = await request.json()
        try:
            a = body["a"]
            b = body["b"]
        except KeyError as e:
            return ResponseWrapper.error(f"Missing required field: {e}", "X_ERROR", 400)
        result = request.app.state.engine.x(a, b)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "X_ERROR", 500)
```

Rules:
- The nested `try` wraps **only** the required-field extraction. Optional
  fields (today's `body.get(...)`) and the engine call stay outside it.
- The 400 path reuses the handler's existing error code.
- Do NOT move `await request.json()` into the nested `try`: a malformed/empty
  body must keep today's wrapped-500 behaviour (outer `except`). Only a
  genuinely missing top-level field becomes 400.
- A deeper `KeyError` (e.g. raw `step["title"]` inside storage) is raised
  outside the nested `try`, so it still falls through to the wrapped 500 —
  never mislabelled "missing field".
- GET handlers are untouched (FastAPI returns 422 for missing query params).

**Files:**
- Modify: `orchestrator/workflow_server/app.py` (handlers listed below)
- Test: `orchestrator/workflow_server/tests/test_app_v2.py`

**Handlers to transform** (path → error code → required fields to extract):

| Handler | Error code | Required fields |
|---|---|---|
| `/project_create` | `PROJECT_CREATE_ERROR` | `name`, `path` (config stays: `{k:v for k,v in body.items() if k not in ("name","path")}`) |
| `/project_switch` | `PROJECT_SWITCH_ERROR` | `project_id` |
| `/session_start` | `SESSION_START_ERROR` | `project_id` (`workflow_type`, `default_rules` stay `.get`) |
| `/session_resume` | `SESSION_RESUME_ERROR` | `project_id` |
| `/interview_question` | `INTERVIEW_QUESTION_ERROR` | `session_id`, `question` |
| `/interview_answer` | `INTERVIEW_ANSWER_ERROR` | `question_id`, `answer` |
| `/interview_complete` | `INTERVIEW_COMPLETE_ERROR` | `session_id` |
| `/analysis_submit` | `ANALYSIS_SUBMIT_ERROR` | `session_id`, `steps` |
| `/analysis_approve` | `ANALYSIS_APPROVE_ERROR` | `session_id` |
| `/analysis_discard` | `ANALYSIS_DISCARD_ERROR` | `session_id` |
| `/step_set_feature` | `STEP_SET_FEATURE_ERROR` | `step_id`, `session_id`, `content` (`filename` stays `.get`) |
| `/step_run_tests` | `STEP_RUN_TESTS_ERROR` | `step_id`, `session_id` |
| `/step_complete` | `STEP_COMPLETE_ERROR` | `step_id`, `session_id` |
| `/step_skip` | `STEP_SKIP_ERROR` | `step_id`, `session_id` (`reason` stays `.get`) |
| `/step_add` | `STEP_ADD_ERROR` | `session_id`, `title`, `order` (see full code below) |
| `/step_remove` | `STEP_REMOVE_ERROR` | `step_id` |
| `/step_edit` | `STEP_EDIT_ERROR` | `step_id` via `.pop` (see full code below) |
| `/step_reorder` | `STEP_REORDER_ERROR` | `session_id`, `step_ids` |
| `/pipeline_set_rules` | `PIPELINE_SET_RULES_ERROR` | `session_id`, `default_rules` |

Two handlers are non-uniform — use this exact code:

`/step_add` (required + optional + `**kwargs`):
```python
@app.post("/step_add")
async def step_add(request: Request) -> Dict[str, Any]:
    """Add a step to a session."""
    start = time.time()
    try:
        body = await request.json()
        try:
            session_id = body["session_id"]
            title = body["title"]
            order = body["order"]
        except KeyError as e:
            return ResponseWrapper.error(f"Missing required field: {e}", "STEP_ADD_ERROR", 400)
        description = body.get("description", "")
        kwargs = {k: v for k, v in body.items()
                  if k not in ("session_id", "title", "description", "order")}
        step_id = request.app.state.engine.add_step(session_id, title, description, order, **kwargs)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"step_id": step_id}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_ADD_ERROR", 500)
```

`/step_edit` (uses `body.pop`):
```python
@app.post("/step_edit")
async def step_edit(request: Request) -> Dict[str, Any]:
    """Edit step fields."""
    start = time.time()
    try:
        body = await request.json()
        try:
            step_id = body.pop("step_id")
        except KeyError as e:
            return ResponseWrapper.error(f"Missing required field: {e}", "STEP_EDIT_ERROR", 400)
        request.app.state.engine.db.update_step(step_id, **body)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"step_id": step_id, "updated": True}, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_EDIT_ERROR", 500)
```

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_app_v2.py` (the file
already has the `client` fixture and imports `pytest` and `json` at the top):

```python
@pytest.mark.parametrize("path, body, code", [
    ("/session_start", {}, "SESSION_START_ERROR"),
    ("/interview_question", {"session_id": "x"}, "INTERVIEW_QUESTION_ERROR"),
    ("/analysis_submit", {"session_id": "x"}, "ANALYSIS_SUBMIT_ERROR"),
    ("/step_add", {"session_id": "x", "title": "t"}, "STEP_ADD_ERROR"),
    ("/step_edit", {}, "STEP_EDIT_ERROR"),
    ("/pipeline_set_rules", {"session_id": "x"}, "PIPELINE_SET_RULES_ERROR"),
])
def test_missing_required_field_returns_400(client, path, body, code):
    r = client.post(path, json=body)
    data = r.json()
    assert data["is_error"] is True
    assert data["metadata"]["status"] == 400
    assert data["metadata"]["error_code"] == code
    payload = json.loads(data["content"][0]["text"])
    assert "Missing required field" in payload["error"]


def test_valid_request_still_succeeds_after_400_guard(client):
    # a well-formed request must be unaffected by the new KeyError guard
    r = client.post("/project_create", json={"name": "ok", "path": "/tmp/ok-400"})
    assert r.json()["is_error"] is False
    payload = json.loads(r.json()["content"][0]["text"])
    assert "project_id" in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_app_v2.py -k "missing_required_field or valid_request_still" -q`
Expected: the 6 parametrized cases FAIL asserting `status == 400` (today the
missing field raises `KeyError` → caught by `except Exception` → `status 500`).
`test_valid_request_still_succeeds_after_400_guard` already passes.

- [ ] **Step 3: Transform every handler in the table**

Apply the canonical transformation to each of the 19 handlers listed above
(using the two full code blocks for `step_add` and `step_edit`). Each handler:
wrap the required-field extraction in a **nested** `try` with
`except KeyError → ResponseWrapper.error(..., <CODE>, 400)`, leaving the outer
`try ... except Exception → ..., 500` (and `await request.json()`, optional
fields, engine call, success) where they are.

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **172 passed** (165 + 7). No pre-existing test regresses — the
change only re-labels the missing-field error class; valid requests and
domain errors (ValueError → 500) are unchanged.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/app.py orchestrator/workflow_server/tests/test_app_v2.py
git commit -m "fix(app): missing required body field returns HTTP 400, not 500"
```

---

### Task 2: Atomic interview-question open

`engine.interview_question` opens an interview in two commits: insert the
question (`db.add_interview_question`), then `db.set_interview_status('open')`.
A crash between them orphans an open question the gate cannot see. This task
folds the status write into `add_interview_question` (one transaction) and
removes the engine's second call.

**Files:**
- Modify: `orchestrator/workflow_server/storage.py` (`add_interview_question`, around lines 332-347)
- Modify: `orchestrator/workflow_server/engine.py` (`interview_question`, line 110-111)
- Test: `orchestrator/workflow_server/tests/test_storage_v2.py`

- [ ] **Step 1: Write the failing test**

Append to `orchestrator/workflow_server/tests/test_storage_v2.py` (the file
already has the `db` fixture):

```python
def test_add_interview_question_opens_interview_atomically(db):
    """add_interview_question sets interview_status='open' AND inserts the row
    in a single transaction (one commit). The status write is the red-first
    lever: the old method left interview_status untouched."""
    pid = db.create_project("atomic", "/tmp/atomic-iq", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("new_project")

    commits = []
    real_commit = db.conn.commit
    db.conn.commit = lambda: (commits.append(1), real_commit())[1]
    try:
        qid = db.add_interview_question(sid, "What does it do?")
    finally:
        db.conn.commit = real_commit

    # both writes landed (status is the red assertion vs. the old code)
    assert db.get_session(sid)["interview_status"] == "open"
    assert db.get_interview_question(qid)["status"] == "open"
    # ...in exactly one transaction (pins atomicity)
    assert len(commits) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_storage_v2.py::test_add_interview_question_opens_interview_atomically -q`
Expected: FAIL — the old `add_interview_question` does not set
`interview_status`, so `db.get_session(sid)["interview_status"] == "open"`
fails (it is `None`).

- [ ] **Step 3: Fold the status write into `add_interview_question`**

In `orchestrator/workflow_server/storage.py`, replace `add_interview_question`
(around lines 332-347) with:

```python
    def add_interview_question(self, session_id: str, question: str) -> str:
        """Insert an open question with the next order AND set the session's
        interview_status='open', in a single transaction (atomic open)."""
        self._require_lock()
        qid = self._new_id()
        row = self.conn.execute(
            'SELECT COALESCE(MAX("order"), 0) + 1 FROM interview_questions '
            "WHERE session_id=?",
            (session_id,),
        ).fetchone()
        self.conn.execute(
            'INSERT INTO interview_questions (id, session_id, "order", question, '
            "status, asked_at) VALUES (?,?,?,?,?,?)",
            (qid, session_id, row[0], question, "open", time.time()),
        )
        self.conn.execute(
            "UPDATE sessions SET interview_status='open' WHERE id=?",
            (session_id,),
        )
        self.conn.commit()
        return qid
```

- [ ] **Step 4: Drop the redundant call in the engine**

In `orchestrator/workflow_server/engine.py`, in `interview_question`, remove
the now-redundant line (currently line 111):

```python
        self.db.set_interview_status(session_id, "open")
```

So the sequence becomes:
```python
        reopened = session.get("interview_status") == "complete"
        qid = self.db.add_interview_question(session_id, question)
        if reopened:
            self.db.add_event(session_id, "interview_reopened",
                              data={"question_id": qid})
```

Leave `set_interview_status` in `storage.py` (still used by
`interview_complete` to set `'complete'`).

- [ ] **Step 5: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **173 passed** (172 + 1). All existing interview tests stay green:
`interview_question` still opens the interview (now via the atomic storage
method) and the gate still fires.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/workflow_server/storage.py orchestrator/workflow_server/engine.py orchestrator/workflow_server/tests/test_storage_v2.py
git commit -m "fix(storage): open interview question atomically — row + status in one transaction"
```

---

### Task 3: Docs + final verification

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `docs/plans/2026-06-08-hardening-batch-design.md` (status line)

- [ ] **Step 1: Update `docs/ROADMAP.md`**

1. Header first line → `Updated: 2026-06-08 (hardening: HTTP 400 + atomic interview open). Order = priority. Each item ships as its own`

2. In `## Delivered`, append:

```markdown
- **Hardening** — missing required POST body fields return HTTP 400 (not 500);
  opening an interview question is atomic (row + `interview_status` in one
  transaction)
```

3. In `## Next`, the `### 1. Hardening backlog` list: **remove** the two
delivered bullets (the HTTP 400 one and the atomic-interview-writes one),
leaving only:

```markdown
### 1. Hardening backlog (small, opportunistic)
- pytest adapter coverage (currently always 0; gate on coverage is
  behave-only and opt-in) — semantic choice, needs its own mini-design
- storage lock semantics: `update_step`/`add_event` and other writes bypass
  `_require_lock` (subtle; in-memory per-instance lock; do isolated)
- `analysis_approve` non-atomic materialization (writes N files to disk;
  declared single-user risk, not SQLite-transactionable)
```

- [ ] **Step 2: Mark the design doc implemented**

In `docs/plans/2026-06-08-hardening-batch-design.md`, change
`**Status:** Approved` to `**Status:** Implemented`.

- [ ] **Step 3: Commit**

```bash
git add docs/ROADMAP.md docs/plans/2026-06-08-hardening-batch-design.md
git commit -m "docs: hardening batch delivered — roadmap + design status"
```

- [ ] **Step 4: Final verification (suite + demo)**

Run from the repo root, exactly:

```bash
PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q
./scripts/demo_bdd_gate.sh
```

Expected: **173 passed**, and the demo exits 0 with its full red → blocked →
fix → green → accepted sequence. Both must succeed before declaring done.
