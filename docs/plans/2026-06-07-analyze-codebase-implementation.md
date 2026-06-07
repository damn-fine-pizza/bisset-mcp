# Analyze Codebase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `analysis_submit`, `analysis_view`, `analysis_approve`, `analysis_discard` so the codebase-analysis outcome becomes a persisted, revisable, audited pipeline proposal that materializes into real steps on approval (design: `docs/plans/2026-06-07-analyze-codebase-design.md`).

**Architecture:** Schema v4 via a new ladder rung: `analysis_status` column on `sessions` + new `proposal_steps` table. Proposal opened/replaced by full re-submit (Gherkin drafts validated at submit time); explicit approval materializes real steps + feature files through the existing `set_feature` flow (order-prefixed filenames so batch writes never collide); conditional gate in `engine.add_step` (interview checked first, then analysis). All logic in `engine.py`; thin endpoints in `app.py`; MCP exposure in `server.py` + `client.py`; analyzer prompt rewritten to drive the tools.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, pytest.

**Conventions (binding):**
- Run all tests with `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q` from the repo root.
- Branch: `dev/feature0014-analyze-codebase` (already created, design doc committed).
- Baseline before Task 1: **132 passed**. Per-task expected counts below are a guide; the running count from the previous task is the truth — if it differs by a constant offset, carry the offset forward instead of stalling.
- NEVER add Co-Authored-By or AI-attribution trailers to commits or PR bodies.
- Subagents MUST NOT run `git checkout` / `git switch`.

---

### Task 1: Schema v4 — `analysis_status` + `proposal_steps` + storage primitives

New ladder rung `_migrate_v3_to_v4`, `SCHEMA_VERSION` 3 → 4. The base v1
schema is frozen; the rung is guarded and idempotent like the existing ones.
Storage gains three primitives: `set_analysis_status`,
`replace_proposal_steps` (delete + re-insert in one commit — the proposal
table always holds the *current* proposal), `list_proposal_steps`.

**Files:**
- Modify: `orchestrator/workflow_server/storage.py` (SCHEMA_VERSION at line 8; new rung after `_migrate_v2_to_v3`; new section after the Interview section)
- Test: `orchestrator/workflow_server/tests/test_storage_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_storage_v2.py` (the file
already has the `db` fixture and the `_build_v2_db` helper):

```python
def _build_v3_db(db_file):
    """A handmade v3 database (v2 schema + interview state + version 3)."""
    import sqlite3
    _build_v2_db(db_file)
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        ALTER TABLE sessions ADD COLUMN interview_status TEXT;
        CREATE TABLE interview_questions (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            "order" INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            asked_at REAL NOT NULL,
            answered_at REAL
        );
        DELETE FROM schema_version;
        INSERT INTO schema_version (version) VALUES (3);
    """)
    conn.commit()
    conn.close()


def test_migration_v3_to_v4_adds_analysis_state(tmp_path):
    from orchestrator.workflow_server.storage import SCHEMA_VERSION
    db_file = str(tmp_path / "v3.db")
    _build_v3_db(db_file)
    db = Storage(db_path=db_file)
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(sessions)").fetchall()]
    assert "analysis_status" in cols
    tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "proposal_steps" in tables
    ver = db.conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert ver == SCHEMA_VERSION
    db.close()


def test_fresh_db_has_analysis_state():
    """A fresh DB walks the ladder up to v4: column + table present."""
    db = Storage(db_path=":memory:")
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(sessions)").fetchall()]
    assert "analysis_status" in cols
    tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "proposal_steps" in tables
    db.close()


def test_set_analysis_status(db):
    pid = db.create_project("legacy", "/tmp/as-app", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("generate_tests")
    assert db.get_session(sid)["analysis_status"] is None
    db.set_analysis_status(sid, "open")
    assert db.get_session(sid)["analysis_status"] == "open"
    db.set_analysis_status(sid, "approved")
    assert db.get_session(sid)["analysis_status"] == "approved"


def test_replace_proposal_steps_roundtrip(db):
    pid = db.create_project("legacy", "/tmp/ps-app", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("generate_tests")
    ids = db.replace_proposal_steps(sid, [
        {"title": "Cover /health", "description": "health checks",
         "feature_draft": "Feature: h"},
        {"title": "Cover /orders"},
    ])
    rows = db.list_proposal_steps(sid)
    assert [r["order"] for r in rows] == [1, 2]
    assert [r["id"] for r in rows] == ids
    assert rows[0]["feature_draft"] == "Feature: h"
    assert rows[0]["created_at"] is not None
    assert rows[1]["feature_draft"] is None
    assert rows[1]["description"] == ""


def test_replace_proposal_steps_overwrites(db):
    pid = db.create_project("legacy", "/tmp/ps-ow", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("generate_tests")
    db.replace_proposal_steps(sid, [{"title": "A"}, {"title": "B"}, {"title": "C"}])
    db.replace_proposal_steps(sid, [{"title": "Solo"}])
    rows = db.list_proposal_steps(sid)
    assert len(rows) == 1
    assert rows[0]["title"] == "Solo"
    assert rows[0]["order"] == 1


def test_proposal_steps_per_session_isolation(db):
    pid = db.create_project("legacy", "/tmp/ps-iso", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid1 = db.create_session("generate_tests")
    sid2 = db.create_session("new_feature")
    db.replace_proposal_steps(sid1, [{"title": "S1-A"}, {"title": "S1-B"}])
    db.replace_proposal_steps(sid2, [{"title": "S2-A"}])
    assert [r["title"] for r in db.list_proposal_steps(sid1)] == ["S1-A", "S1-B"]
    assert [r["title"] for r in db.list_proposal_steps(sid2)] == ["S2-A"]
    db.replace_proposal_steps(sid2, [])
    assert db.list_proposal_steps(sid2) == []
    assert len(db.list_proposal_steps(sid1)) == 2
```

Note: `replace_proposal_steps(sid, [])` is legal at storage level (it just
empties the table for the session); the non-empty invariant is engine-level,
same split as the interview's one-open-question invariant.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_storage_v2.py -q`

Expected: the 6 new tests FAIL (`analysis_status` column missing /
`AttributeError: 'Storage' object has no attribute 'set_analysis_status'`).
The pre-existing tests still pass.

- [ ] **Step 3: Implement schema v4 + storage primitives**

In `orchestrator/workflow_server/storage.py`:

1. Line 8, bump the ceiling:

```python
SCHEMA_VERSION = 4
```

2. After `_migrate_v2_to_v3` (after line 220), add the new rung:

```python
    @staticmethod
    def _migrate_v3_to_v4(cur: sqlite3.Cursor) -> None:
        """v3 -> v4: analysis proposal as session state (guarded: ALTER has no IF NOT EXISTS)."""
        existing = {r[1] for r in cur.execute("PRAGMA table_info(sessions)").fetchall()}
        if "analysis_status" not in existing:
            cur.execute("ALTER TABLE sessions ADD COLUMN analysis_status TEXT")
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS proposal_steps (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            "order" INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            feature_draft TEXT,
            created_at REAL NOT NULL
        );
        """)
```

3. After the `# ── Interview ──` section (after `answer_interview_question`,
line 373), add:

```python
    # ── Analysis ──────────────────────────────────────────────────────────────

    def set_analysis_status(self, session_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET analysis_status=? WHERE id=?",
            (status, session_id),
        )
        self.conn.commit()

    def replace_proposal_steps(self, session_id: str, steps: list[dict]) -> list[str]:
        """Replace the session's proposal with `steps` (single commit).

        Each step dict: title (required), description, feature_draft.
        The table always holds the *current* proposal; revision history
        lives in the event log. Returns the new row ids in order.
        """
        self._require_lock()
        self.conn.execute(
            "DELETE FROM proposal_steps WHERE session_id=?", (session_id,)
        )
        ids = []
        now = time.time()
        for idx, step in enumerate(steps, start=1):
            row_id = self._new_id()
            self.conn.execute(
                'INSERT INTO proposal_steps (id, session_id, "order", title, '
                "description, feature_draft, created_at) VALUES (?,?,?,?,?,?,?)",
                (row_id, session_id, idx, step["title"],
                 step.get("description", ""), step.get("feature_draft"), now),
            )
            ids.append(row_id)
        self.conn.commit()
        return ids

    def list_proposal_steps(self, session_id: str) -> list[dict]:
        return self._fetchall_dict(
            'SELECT * FROM proposal_steps WHERE session_id=? ORDER BY "order"',
            (session_id,),
        )
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **138 passed** (132 + 6). In particular the lineage-sentinel tests
and `test_migration_v2_to_v3_adds_interview_state` must still pass: v2/v3 DBs
now walk the ladder to v4 and those tests assert `ver == SCHEMA_VERSION`,
which follows the bumped ceiling automatically.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/storage.py orchestrator/workflow_server/tests/test_storage_v2.py
git commit -m "feat(storage): schema v4 — analysis_status + proposal_steps with stepwise rung"
```

---

### Task 2: Engine — `analysis_submit` / `analysis_view`

Submit opens (or replaces) the proposal. Gherkin drafts are validated here
with `check_syntax` so approval can never fail on syntax: per-step structured
errors, nothing written (same non-exception contract as `set_feature`).
Re-submit on `open` revises (audited); re-submit on a terminal status reopens
and re-arms the gate.

**Files:**
- Modify: `orchestrator/workflow_server/engine.py` (new section after the Interview section, i.e. after `_interview_block`, line 191)
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py` (the file
already defines the `engine` fixture and the module-level `VALID_FEATURE`
constant at line 156 — reuse both):

```python
def test_analysis_submit_opens_proposal(engine):
    pid = engine.create_project("legacy", "/tmp/an-app")
    sid = engine.start_session(pid, "generate_tests")
    r = engine.analysis_submit(sid, [
        {"title": "Cover health", "description": "d", "feature_draft": VALID_FEATURE},
        {"title": "Cover orders"},
    ])
    assert r["submitted"] is True
    assert r["analysis_status"] == "open"
    assert r["steps_proposed"] == 2
    assert r["features_drafted"] == 1
    assert r["revised"] is False
    assert engine.db.get_session(sid)["analysis_status"] == "open"
    rows = engine.db.list_proposal_steps(sid)
    assert [row["title"] for row in rows] == ["Cover health", "Cover orders"]
    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "analysis_submitted" for e in events)


def test_analysis_submit_rejects_empty_list_and_titles(engine):
    pid = engine.create_project("legacy", "/tmp/an-empty")
    sid = engine.start_session(pid, "generate_tests")
    with pytest.raises(ValueError, match="at least one step"):
        engine.analysis_submit(sid, [])
    with pytest.raises(ValueError, match="empty title"):
        engine.analysis_submit(sid, [{"title": "  "}])
    assert engine.db.get_session(sid)["analysis_status"] is None
    assert engine.db.list_proposal_steps(sid) == []


def test_analysis_submit_rejects_bad_gherkin_without_writing(engine):
    pid = engine.create_project("legacy", "/tmp/an-bad")
    sid = engine.start_session(pid, "generate_tests")
    r = engine.analysis_submit(sid, [
        {"title": "Good", "feature_draft": VALID_FEATURE},
        {"title": "Bad", "feature_draft": "this is not gherkin at all"},
    ])
    assert r["submitted"] is False
    assert r["errors"][0]["order"] == 2
    assert r["errors"][0]["title"] == "Bad"
    assert r["errors"][0]["errors"]  # check_syntax findings
    assert engine.db.get_session(sid)["analysis_status"] is None
    assert engine.db.list_proposal_steps(sid) == []


def test_analysis_resubmit_open_revises(engine):
    pid = engine.create_project("legacy", "/tmp/an-rev")
    sid = engine.start_session(pid, "generate_tests")
    engine.analysis_submit(sid, [{"title": "A1"}, {"title": "A2"}, {"title": "A3"}])
    r2 = engine.analysis_submit(sid, [{"title": "B1"}, {"title": "B2"}])
    assert r2["revised"] is True
    assert [row["title"] for row in engine.db.list_proposal_steps(sid)] == ["B1", "B2"]
    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "analysis_revised" for e in events)


def test_analysis_resubmit_after_terminal_reopens(engine):
    pid = engine.create_project("legacy", "/tmp/an-reopen")
    sid = engine.start_session(pid, "generate_tests")
    engine.analysis_submit(sid, [{"title": "A"}])
    engine.db.set_analysis_status(sid, "discarded")
    r = engine.analysis_submit(sid, [{"title": "Fresh"}])
    assert r["revised"] is False
    assert engine.db.get_session(sid)["analysis_status"] == "open"
    submitted = [e for e in engine.db.list_events(sid)
                 if e["event_type"] == "analysis_submitted"]
    assert any(e["data"] and e["data"].get("previous_status") == "discarded"
               for e in submitted)


def test_analysis_submit_unknown_session(engine):
    with pytest.raises(ValueError, match="Session not found"):
        engine.analysis_submit("nope", [{"title": "X"}])


def test_analysis_view(engine):
    pid = engine.create_project("legacy", "/tmp/an-view")
    sid = engine.start_session(pid, "generate_tests")
    assert engine.analysis_view(sid) == {"analysis_status": None, "steps": []}
    engine.analysis_submit(sid, [{"title": "A", "feature_draft": VALID_FEATURE}])
    v = engine.analysis_view(sid)
    assert v["analysis_status"] == "open"
    assert v["steps"][0]["order"] == 1
    assert v["steps"][0]["title"] == "A"
    assert v["steps"][0]["feature_draft"] == VALID_FEATURE
    with pytest.raises(ValueError, match="Session not found"):
        engine.analysis_view("nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -q`
Expected: the 7 new tests FAIL with `AttributeError: 'WorkflowEngine' object has no attribute 'analysis_submit'`.

- [ ] **Step 3: Implement `analysis_submit` / `analysis_view`**

In `orchestrator/workflow_server/engine.py`, after `_interview_block`
(line 191), add a new section:

```python
    # -- Analysis -----------------------------------------------------------------

    def analysis_submit(self, session_id: str, steps: list[dict]) -> dict:
        """Open (or replace) the analysis proposal for a session.

        Gherkin drafts are validated here so analysis_approve can never fail
        on syntax. Re-submitting an open proposal replaces it (audited as
        analysis_revised); re-submitting a terminal one opens a fresh
        proposal and re-arms the step_add gate.
        """
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if not isinstance(steps, list) or not steps:
            raise ValueError(
                "Proposal must contain at least one step "
                "({title, description?, feature_draft?})."
            )
        cleaned = []
        errors = []
        for idx, step in enumerate(steps, start=1):
            title = (step.get("title") or "").strip()
            if not title:
                raise ValueError(f"Proposal step {idx} has an empty title.")
            draft = step.get("feature_draft")
            if draft is not None:
                draft_errors = check_syntax(draft)
                if draft_errors:
                    errors.append({"order": idx, "title": title,
                                   "errors": draft_errors})
            cleaned.append({"title": title,
                            "description": (step.get("description") or "").strip(),
                            "feature_draft": draft})
        if errors:
            return {"submitted": False, "errors": errors}

        previous = session.get("analysis_status")
        self.db.replace_proposal_steps(session_id, cleaned)
        self.db.set_analysis_status(session_id, "open")
        drafted = sum(1 for s in cleaned if s["feature_draft"])
        event = "analysis_revised" if previous == "open" else "analysis_submitted"
        data = {"steps": len(cleaned), "features_drafted": drafted}
        if previous and previous != "open":
            data["previous_status"] = previous
        self.db.add_event(session_id, event, data=data)
        return {"submitted": True, "analysis_status": "open",
                "steps_proposed": len(cleaned), "features_drafted": drafted,
                "revised": previous == "open"}

    def analysis_view(self, session_id: str) -> dict:
        """Read the persisted proposal (status + proposed steps with drafts)."""
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        status = session.get("analysis_status")
        if status is None:
            return {"analysis_status": None, "steps": []}
        steps = self.db.list_proposal_steps(session_id)
        return {"analysis_status": status,
                "steps": [{"order": s["order"], "title": s["title"],
                           "description": s["description"],
                           "feature_draft": s["feature_draft"]}
                          for s in steps]}
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **145 passed** (138 + 7).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/engine.py orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "feat(engine): analysis_submit / analysis_view — proposal as revisable session state"
```

---

### Task 3: Engine — `analysis_approve` / `analysis_discard` + conditional gate

Approval materializes the proposal: real steps appended after any existing
ones, drafts written to disk through the existing `set_feature` flow. The
filename is **explicitly order-prefixed** (`01-<slug>.feature`): batch
materialization writes N files in one shot, and two titles that slugify to
the same name must never overwrite each other on disk. Non-atomic by declared
design (see the design doc): the loop is ordered so a partial failure leaves
a consistent prefix and the proposal still `open`.

The `step_add` gate gains the analysis check **after** the interview check
(fixed order, each with its own actionable error). `session_status` gains an
`analysis` block alongside the existing `interview` block.

**Files:**
- Modify: `orchestrator/workflow_server/engine.py` (extend the Analysis section; `add_step` lines 195-216; `session_status` lines 76-89)
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py`:

```python
def test_analysis_approve_materializes(engine, tmp_path):
    pid = engine.create_project("legacy", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "generate_tests")
    engine.analysis_submit(sid, [
        {"title": "Cover health", "description": "d1", "feature_draft": VALID_FEATURE},
        {"title": "Cover orders", "description": "d2"},
    ])
    r = engine.analysis_approve(sid)
    assert r["analysis_status"] == "approved"
    assert r["steps_created"] == 2
    assert r["features_written"] == 1
    assert r["steps"][0]["proposal_order"] == 1
    assert r["steps"][0]["feature_path"] == "features/01-cover-health.feature"
    assert r["steps"][1]["feature_path"] is None
    steps = engine.db.list_steps(sid)
    assert [s["title"] for s in steps] == ["Cover health", "Cover orders"]
    assert steps[0]["feature_path"] == "features/01-cover-health.feature"
    written = (tmp_path / "features" / "01-cover-health.feature").read_text()
    assert written == VALID_FEATURE
    assert engine.db.get_session(sid)["analysis_status"] == "approved"
    types = {e["event_type"] for e in engine.db.list_events(sid)}
    assert {"analysis_approved", "step_added", "feature_set"} <= types


def test_analysis_approve_disambiguates_colliding_titles(engine, tmp_path):
    """Two titles that slugify identically must produce two distinct files."""
    pid = engine.create_project("legacy", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "generate_tests")
    second = VALID_FEATURE.replace("Feature: Calculator", "Feature: Calculator bis")
    engine.analysis_submit(sid, [
        {"title": "Cover /health", "feature_draft": VALID_FEATURE},
        {"title": "Cover health", "feature_draft": second},
    ])
    r = engine.analysis_approve(sid)
    paths = [s["feature_path"] for s in r["steps"]]
    assert len(set(paths)) == 2
    assert (tmp_path / "features" / "01-cover-health.feature").read_text() == VALID_FEATURE
    assert (tmp_path / "features" / "02-cover-health.feature").read_text() == second


def test_analysis_approve_requires_open_proposal(engine):
    pid = engine.create_project("legacy", "/tmp/an-noopen")
    sid = engine.start_session(pid, "generate_tests")
    with pytest.raises(ValueError, match="No open analysis proposal"):
        engine.analysis_approve(sid)
    engine.db.set_analysis_status(sid, "approved")
    with pytest.raises(ValueError, match="No open analysis proposal"):
        engine.analysis_approve(sid)


def test_analysis_approve_blocked_by_open_interview(engine, tmp_path):
    pid = engine.create_project("legacy", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "generate_tests")
    engine.analysis_submit(sid, [{"title": "A"}])
    engine.interview_question(sid, "What is this project?")
    with pytest.raises(ValueError, match="interview_complete"):
        engine.analysis_approve(sid)
    assert engine.db.get_session(sid)["analysis_status"] == "open"
    assert engine.db.list_steps(sid) == []


def test_analysis_approve_appends_after_existing_steps(engine, tmp_path):
    pid = engine.create_project("legacy", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "generate_tests")
    engine.add_step(sid, "Manual step", "d", 5)
    engine.analysis_submit(sid, [{"title": "Proposed"}])
    r = engine.analysis_approve(sid)
    new_step = engine.db.get_step(r["steps"][0]["step_id"])
    assert new_step["order"] == 6


def test_analysis_discard(engine):
    pid = engine.create_project("legacy", "/tmp/an-disc")
    sid = engine.start_session(pid, "generate_tests")
    engine.analysis_submit(sid, [{"title": "A"}, {"title": "B"}])
    r = engine.analysis_discard(sid)
    assert r == {"analysis_status": "discarded", "steps_discarded": 2}
    assert engine.db.get_session(sid)["analysis_status"] == "discarded"
    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "analysis_discarded" for e in events)
    # rows remain readable after discard
    assert len(engine.analysis_view(sid)["steps"]) == 2


def test_analysis_discard_requires_open(engine):
    pid = engine.create_project("legacy", "/tmp/an-disc2")
    sid = engine.start_session(pid, "generate_tests")
    with pytest.raises(ValueError, match="No open analysis proposal"):
        engine.analysis_discard(sid)


def test_add_step_gated_by_open_proposal(engine):
    pid = engine.create_project("legacy", "/tmp/an-gate")
    sid = engine.start_session(pid, "generate_tests")
    engine.analysis_submit(sid, [{"title": "A"}])
    with pytest.raises(ValueError, match="analysis_approve"):
        engine.add_step(sid, "Manual", "d", 1)
    # a terminal state unblocks
    engine.analysis_discard(sid)
    step_id = engine.add_step(sid, "Manual", "d", 1)
    assert engine.db.get_step(step_id) is not None


def test_add_step_gate_checks_interview_first(engine):
    """Both gates open: the interview error wins (fixed check order)."""
    pid = engine.create_project("legacy", "/tmp/an-order")
    sid = engine.start_session(pid, "generate_tests")
    engine.analysis_submit(sid, [{"title": "A"}])
    engine.interview_question(sid, "Pending question?")
    with pytest.raises(ValueError, match="Interview in progress"):
        engine.add_step(sid, "Manual", "d", 1)


def test_session_status_analysis_block(engine):
    pid = engine.create_project("legacy", "/tmp/an-block")
    sid = engine.start_session(pid, "generate_tests")
    assert engine.session_status(sid)["analysis"] is None
    engine.analysis_submit(sid, [
        {"title": "A", "feature_draft": VALID_FEATURE}, {"title": "B"},
    ])
    block = engine.session_status(sid)["analysis"]
    assert block["status"] == "open"
    assert block["steps_proposed"] == 2
    assert block["features_drafted"] == 1
    assert block["steps"][0] == {"order": 1, "title": "A", "has_draft": True}
    assert block["steps"][1] == {"order": 2, "title": "B", "has_draft": False}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -q`
Expected: the 10 new tests FAIL (`analysis_approve` missing; gate/status
tests fail because `add_step` and `session_status` don't know analysis yet).

- [ ] **Step 3: Implement approve/discard, gate, status block**

In `orchestrator/workflow_server/engine.py`:

1. Append to the Analysis section (after `analysis_view`):

```python
    def analysis_approve(self, session_id: str) -> dict:
        """Materialize the open proposal into real steps (+ features on disk).

        Non-atomic by declared design (see the design doc): the loop is
        ordered so a partial failure leaves a consistent prefix of real
        steps and the proposal still open.
        """
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        status = session.get("analysis_status")
        if status != "open":
            raise ValueError(
                f"No open analysis proposal (status: {status}). Submit one "
                "via analysis_submit before approving."
            )
        if session.get("interview_status") == "open":
            raise ValueError(
                "Interview in progress: complete it via interview_complete "
                "before approving the analysis proposal."
            )
        proposal = self.db.list_proposal_steps(session_id)
        existing = self.db.list_steps(session_id)
        next_order = max((s["order"] for s in existing), default=0) + 1
        created = []
        features_written = 0
        for offset, p in enumerate(proposal):
            order = next_order + offset
            # storage-level add: the engine gate guards the manual tool
            # path, not this internal promotion
            step_id = self.db.add_step(session_id, p["title"],
                                       p["description"], order)
            self.db.add_event(session_id, "step_added", step_id=step_id,
                              data={"title": p["title"], "order": order,
                                    "source": "analysis"})
            feature_path = None
            if p["feature_draft"]:
                # batch write: titles may slugify identically — the order
                # prefix guarantees one file per proposed step
                result = self.set_feature(
                    step_id, session_id, p["feature_draft"],
                    filename=f"{p['order']:02d}-{derive_filename(p['title'])}")
                if not result["written"]:
                    # unreachable: drafts are validated at submit time
                    raise ValueError(
                        f"Feature draft for proposal step {p['order']} failed "
                        f"validation at approve time: {result['errors']}"
                    )
                feature_path = result["feature_path"]
                features_written += 1
            created.append({"proposal_order": p["order"], "step_id": step_id,
                            "order": order, "feature_path": feature_path})
        self.db.set_analysis_status(session_id, "approved")
        self.db.add_event(session_id, "analysis_approved",
                          data={"steps_created": len(created),
                                "features_written": features_written})
        return {"analysis_status": "approved", "steps": created,
                "steps_created": len(created),
                "features_written": features_written}

    def analysis_discard(self, session_id: str) -> dict:
        """Discard the open proposal; rows remain readable via analysis_view."""
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        status = session.get("analysis_status")
        if status != "open":
            raise ValueError(
                f"No open analysis proposal to discard (status: {status})."
            )
        steps = self.db.list_proposal_steps(session_id)
        self.db.set_analysis_status(session_id, "discarded")
        self.db.add_event(session_id, "analysis_discarded",
                          data={"steps": len(steps)})
        return {"analysis_status": "discarded", "steps_discarded": len(steps)}

    def _analysis_block(self, session_id: str, session: dict) -> dict | None:
        """Analysis summary for status responses (None = never started)."""
        status = session.get("analysis_status")
        if status is None:
            return None
        steps = self.db.list_proposal_steps(session_id)
        return {"status": status,
                "steps_proposed": len(steps),
                "features_drafted": sum(1 for s in steps if s["feature_draft"]),
                "steps": [{"order": s["order"], "title": s["title"],
                           "has_draft": bool(s["feature_draft"])}
                          for s in steps]}
```

2. In `session_status` (lines 76-89), add the `analysis` key right after the
`interview` key:

```python
            "interview": self._interview_block(session_id, session) if session else None,
            "analysis": self._analysis_block(session_id, session) if session else None,
```

3. In `add_step` (lines 195-216), after the existing interview gate (after
the second `raise ValueError(...)` of the interview branch) and before
`step_id = self.db.add_step(...)`, add:

```python
        if session and session.get("analysis_status") == "open":
            n = len(self.db.list_proposal_steps(session_id))
            raise ValueError(
                f"Analysis proposal pending: an open proposal with {n} "
                "step(s) exists. Approve it with analysis_approve or discard "
                "it with analysis_discard before adding steps manually."
            )
```

And update the docstring:

```python
        """Add a step to a session (gated while an interview or an analysis
        proposal is open; check order: interview first, then analysis)."""
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **155 passed** (145 + 10). `derive_filename` is already imported in
`engine.py` (line 12).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/engine.py orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "feat(engine): analysis_approve / analysis_discard, conditional gate on step_add, analysis status block"
```

---

### Task 4: HTTP endpoints — `/analysis_*` + analysis block in `session_resume`

Thin endpoints, zero logic, same wrapper/error-code style as the interview
endpoints. `session_resume` gains the `analysis` block alongside `interview`.

**Files:**
- Modify: `orchestrator/workflow_server/app.py` (new section after the Interview endpoints, line 285; `session_resume` lines 203-215)
- Test: `orchestrator/workflow_server/tests/test_app_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_app_v2.py` (the file
already has the `client` fixture and the module-level `VALID_FEATURE`
constant at line 212):

```python
def test_analysis_flow_endpoints(client, tmp_path):
    r = client.post("/project_create", json={
        "name": "legacy", "path": str(tmp_path), "adapter": "behave"})
    pid = json.loads(r.json()["content"][0]["text"])["project_id"]
    r = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "generate_tests"})
    sid = json.loads(r.json()["content"][0]["text"])["session_id"]

    r = client.post("/analysis_submit", json={"session_id": sid, "steps": [
        {"title": "Cover health", "feature_draft": VALID_FEATURE},
        {"title": "Cover orders", "description": "order flows"},
    ]})
    assert r.json()["is_error"] is False
    body = json.loads(r.json()["content"][0]["text"])
    assert body["submitted"] is True
    assert body["steps_proposed"] == 2

    r = client.get(f"/analysis_view?session_id={sid}")
    body = json.loads(r.json()["content"][0]["text"])
    assert body["analysis_status"] == "open"
    assert len(body["steps"]) == 2

    r = client.post("/analysis_approve", json={"session_id": sid})
    assert r.json()["is_error"] is False
    body = json.loads(r.json()["content"][0]["text"])
    assert body["steps_created"] == 2
    assert (tmp_path / "features" / "01-cover-health.feature").exists()


def test_analysis_submit_rejects_bad_gherkin(client):
    r = client.post("/project_create", json={
        "name": "legacy", "path": "/tmp/an-api-bad"})
    pid = json.loads(r.json()["content"][0]["text"])["project_id"]
    r = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "generate_tests"})
    sid = json.loads(r.json()["content"][0]["text"])["session_id"]

    r = client.post("/analysis_submit", json={"session_id": sid, "steps": [
        {"title": "Bad", "feature_draft": "not gherkin"},
    ]})
    # same contract as step_set_feature: structured refusal, not a transport error
    assert r.json()["is_error"] is False
    body = json.loads(r.json()["content"][0]["text"])
    assert body["submitted"] is False
    assert body["errors"][0]["title"] == "Bad"


def test_step_add_blocked_while_proposal_open(client):
    r = client.post("/project_create", json={
        "name": "legacy", "path": "/tmp/an-api-gate"})
    pid = json.loads(r.json()["content"][0]["text"])["project_id"]
    r = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "generate_tests"})
    sid = json.loads(r.json()["content"][0]["text"])["session_id"]

    client.post("/analysis_submit", json={"session_id": sid, "steps": [
        {"title": "Proposed"},
    ]})
    r = client.post("/step_add", json={"session_id": sid, "title": "S1", "order": 1})
    assert r.json()["is_error"] is True
    err = json.loads(r.json()["content"][0]["text"])["error"]
    assert "analysis_approve" in err


def test_analysis_discard_endpoint(client):
    r = client.post("/project_create", json={
        "name": "legacy", "path": "/tmp/an-api-disc"})
    pid = json.loads(r.json()["content"][0]["text"])["project_id"]
    r = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "generate_tests"})
    sid = json.loads(r.json()["content"][0]["text"])["session_id"]

    client.post("/analysis_submit", json={"session_id": sid, "steps": [
        {"title": "Proposed"},
    ]})
    r = client.post("/analysis_discard", json={"session_id": sid})
    body = json.loads(r.json()["content"][0]["text"])
    assert body["analysis_status"] == "discarded"
    # gate released
    r = client.post("/step_add", json={"session_id": sid, "title": "S1", "order": 1})
    assert r.json()["is_error"] is False


def test_session_resume_reports_analysis_block(client):
    r = client.post("/project_create", json={
        "name": "legacy", "path": "/tmp/an-api-resume"})
    pid = json.loads(r.json()["content"][0]["text"])["project_id"]
    r = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "generate_tests"})
    sid = json.loads(r.json()["content"][0]["text"])["session_id"]

    # before any analysis: block is null
    r = client.post("/session_resume", json={"project_id": pid})
    body = json.loads(r.json()["content"][0]["text"])
    assert body["session_id"] == sid
    assert body["analysis"] is None

    client.post("/analysis_submit", json={"session_id": sid, "steps": [
        {"title": "Proposed"},
    ]})
    r = client.post("/session_resume", json={"project_id": pid})
    body = json.loads(r.json()["content"][0]["text"])
    assert body["analysis"]["status"] == "open"
    assert body["analysis"]["steps_proposed"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_app_v2.py -q`
Expected: the 5 new tests FAIL (404 on `/analysis_*`; `analysis` key missing
from the resume payload).

- [ ] **Step 3: Implement the endpoints**

In `orchestrator/workflow_server/app.py`:

1. After the Interview endpoints block (after `interview_complete`,
line 285), add:

```python
# ============================================================================
# Analysis
# ============================================================================

@app.post("/analysis_submit")
async def analysis_submit(request: Request) -> Dict[str, Any]:
    """Open (or replace) the analysis proposal: step list + Gherkin drafts."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.analysis_submit(
            body["session_id"], body["steps"])
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "ANALYSIS_SUBMIT_ERROR", 500)


@app.get("/analysis_view")
async def analysis_view(request: Request, session_id: str) -> Dict[str, Any]:
    """Read the session's analysis proposal (status + proposed steps)."""
    start = time.time()
    try:
        result = request.app.state.engine.analysis_view(session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "ANALYSIS_VIEW_ERROR", 500)


@app.post("/analysis_approve")
async def analysis_approve(request: Request) -> Dict[str, Any]:
    """Materialize the open proposal into real steps + feature files."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.analysis_approve(body["session_id"])
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "ANALYSIS_APPROVE_ERROR", 500)


@app.post("/analysis_discard")
async def analysis_discard(request: Request) -> Dict[str, Any]:
    """Discard the open proposal; unblocks manual step_add."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.analysis_discard(body["session_id"])
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "ANALYSIS_DISCARD_ERROR", 500)
```

2. In `session_resume` (lines 203-215), replace the body of the `try` block
so both blocks come from one `session_status` call:

```python
        body = await request.json()
        project_id = body["project_id"]
        sid = request.app.state.engine.resume_session(project_id)
        status = request.app.state.engine.session_status(sid)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({
            "session_id": sid,
            "interview": status["interview"],
            "analysis": status["analysis"],
        }, duration)
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **160 passed** (155 + 5). The pre-existing resume tests
(`test_session_resume_reports_pending_question`,
`test_session_resume_without_interview_has_null_block`) must still pass —
the payload change is additive.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/app.py orchestrator/workflow_server/tests/test_app_v2.py
git commit -m "feat(app): /analysis_* endpoints, analysis block in session_resume"
```

---

### Task 5: MCP exposure + analyzer prompt rewrite

Four MCP tool definitions; `analysis_view` routed as GET. The
`bisset/analyzer` prompt is rewritten to drive the new tools (as the
interviewer prompt was for the interview tools): submit the proposal, wait
for human review, revise by re-submitting, approve only on explicit human
confirmation, never bypass with `step_add`.

**Files:**
- Modify: `orchestrator/mcp_server/server.py` (tool list, after the Interview block, line 88)
- Modify: `orchestrator/mcp_server/client.py` (`_GET_TOOLS`, lines 15-27)
- Modify: `orchestrator/mcp_server/prompts.py` (`bisset/analyzer`, lines 93-114)
- Test: `orchestrator/mcp_server/tests/test_client_v2.py`, `orchestrator/mcp_server/tests/test_prompts_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/mcp_server/tests/test_client_v2.py`:

```python
def test_analysis_tools_exposed():
    from orchestrator.mcp_server.server import BissetMCPServer
    tools = {t["name"] for t in BissetMCPServer()._build_tools()}
    assert {"analysis_submit", "analysis_view",
            "analysis_approve", "analysis_discard"} <= tools


def test_analysis_tools_routing():
    from orchestrator.mcp_server.client import _GET_TOOLS
    # the read goes through GET, the writes through POST
    assert "analysis_view" in _GET_TOOLS
    assert "analysis_submit" not in _GET_TOOLS
    assert "analysis_approve" not in _GET_TOOLS
    assert "analysis_discard" not in _GET_TOOLS
```

Append to `orchestrator/mcp_server/tests/test_prompts_v2.py`:

```python
def test_analyzer_prompt_mentions_analysis_tools():
    reg = PromptRegistry()
    text = reg.render("bisset/analyzer", {}, {})
    for tool in ("analysis_submit", "analysis_view",
                 "analysis_approve", "analysis_discard"):
        assert tool in text
    # the prompt must forbid bypassing the proposal with manual step_add
    assert "step_add" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/mcp_server/ -q`
Expected: the 3 new tests FAIL (tools missing, prompt without the tool names).

- [ ] **Step 3: Implement exposure + prompt**

1. In `orchestrator/mcp_server/client.py`, add to `_GET_TOOLS` (after
`"step_validate_feature",`):

```python
    "analysis_view",
```

2. In `orchestrator/mcp_server/server.py`, after the Interview tool block
(after the `interview_complete` entry, line 88), add:

```python
            # Analysis
            {"name": "analysis_submit",
             "description": "Submit the proposed pipeline from codebase analysis: ordered steps with optional Gherkin drafts. Re-submitting an open proposal revises it. Check `submitted` in the response: false means a draft failed Gherkin validation (per-step errors) and nothing was saved",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"},
                 "steps": {"type": "array", "items": {"type": "object", "properties": {
                     "title": {"type": "string"},
                     "description": {"type": "string"},
                     "feature_draft": {"type": "string"},
                 }, "required": ["title"]}},
             }, "required": ["session_id", "steps"]}},
            {"name": "analysis_view",
             "description": "View the session's analysis proposal (status + proposed steps with drafts)",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"},
             }, "required": ["session_id"]}},
            {"name": "analysis_approve",
             "description": "Approve the open analysis proposal: materializes real steps and writes feature drafts to disk. Requires no open interview. Call only on explicit human confirmation",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"},
             }, "required": ["session_id"]}},
            {"name": "analysis_discard",
             "description": "Discard the open analysis proposal and unblock manual step_add",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"},
             }, "required": ["session_id"]}},
```

3. In `orchestrator/mcp_server/prompts.py`, replace the whole
`bisset/analyzer` registration (lines 93-114) with:

```python
        self._prompts["bisset/analyzer"] = PromptTemplate(
            "bisset/analyzer",
            """You are analyzing an existing codebase to propose a development pipeline.

Project: {{project.name}}
Path: {{project.path}}

Your role:
- Analyze the codebase: API endpoints and contracts, data models and relationships, business logic and rules, UI components and interactions
- Derive an ordered list of pipeline steps; for each, where possible, draft a Gherkin feature that verifies current behavior
- Submit the proposal to Bisset with analysis_submit (one call, full step list, feature_draft per step) — do NOT create steps manually with step_add while a proposal is open
- Walk the human through the proposal (analysis_view shows the persisted state); revise it by re-submitting the complete list with analysis_submit
- Only on explicit human confirmation call analysis_approve: it materializes real steps and writes the feature drafts to disk
- If the human rejects the proposal entirely, call analysis_discard

Directory structure:
{{context.directory_structure}}

Relevant files:
{{context.relevant_files}}
"""
        )
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **163 passed** (160 + 3).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/mcp_server/server.py orchestrator/mcp_server/client.py orchestrator/mcp_server/prompts.py orchestrator/mcp_server/tests/test_client_v2.py orchestrator/mcp_server/tests/test_prompts_v2.py
git commit -m "feat(mcp): expose analysis tools, rewrite bisset/analyzer to drive them"
```

---

### Task 6: E2E — full analysis lifecycle over HTTP

Mirror of `test_interview_lifecycle`: submit → gate blocks `step_add` →
resume reports the proposal → revise → approve → steps + feature on disk →
gate open → audit trail.

**Files:**
- Test: `orchestrator/tests/test_e2e.py`

- [ ] **Step 1: Write the failing test**

Append to `orchestrator/tests/test_e2e.py` (the file already has `_payload`
and the `client` fixture):

```python
def test_analysis_lifecycle(client, tmp_path):
    """submit -> gate blocks step_add -> resume reports proposal -> revise
    -> approve -> steps + feature on disk -> step_add ok -> audit trail."""
    r = client.post("/project_create", json={
        "name": "analysis-e2e", "path": str(tmp_path), "adapter": "behave",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "generate_tests",
    })
    sid = _payload(r)["session_id"]

    draft = ("Feature: Health\n"
             "  Scenario: Service is up\n"
             "    Given the API is running\n"
             "    When I GET /health\n"
             "    Then I receive 200\n")

    # 1. Claude submits the analyzed pipeline as a proposal
    r = client.post("/analysis_submit", json={"session_id": sid, "steps": [
        {"title": "Cover health", "feature_draft": draft},
        {"title": "Cover orders", "description": "order flows"},
    ]})
    assert _payload(r)["submitted"] is True

    # 2. The gate blocks manual step_add while the proposal is open
    r = client.post("/step_add", json={"session_id": sid, "title": "S1", "order": 1})
    assert r.json()["is_error"] is True
    assert "analysis_approve" in _payload(r)["error"]

    # 3. Resume mid-proposal: the analysis block comes back
    r = client.post("/session_resume", json={"project_id": pid})
    body = _payload(r)
    assert body["session_id"] == sid
    assert body["analysis"]["status"] == "open"
    assert body["analysis"]["steps_proposed"] == 2

    # 4. Revision: re-submitting replaces the whole list
    r = client.post("/analysis_submit", json={"session_id": sid, "steps": [
        {"title": "Cover health", "feature_draft": draft},
    ]})
    assert _payload(r)["revised"] is True

    # 5. Approval materializes: real step + feature file on disk
    r = client.post("/analysis_approve", json={"session_id": sid})
    body = _payload(r)
    assert body["steps_created"] == 1
    assert body["features_written"] == 1
    assert (tmp_path / "features" / "01-cover-health.feature").read_text() == draft

    # 6. Gate open again
    r = client.post("/step_add", json={"session_id": sid, "title": "Manual", "order": 99})
    assert r.json()["is_error"] is False

    # 7. Full audit trail
    r = client.get(f"/event_log?session_id={sid}")
    types = {e["event_type"] for e in _payload(r)["events"]}
    assert {"analysis_submitted", "analysis_revised", "analysis_approved",
            "step_added", "feature_set"} <= types
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/tests/test_e2e.py -q`
Expected: PASS immediately — every layer it crosses was TDD'd in Tasks 1-5.
This test pins the integrated contract at the HTTP boundary. If it fails,
something in the integration is genuinely broken: investigate, do not adapt
the test.

- [ ] **Step 3: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **164 passed** (163 + 1).

- [ ] **Step 4: Commit**

```bash
git add orchestrator/tests/test_e2e.py
git commit -m "test(e2e): analysis lifecycle — gate, resume, revision, materialization, audit trail"
```

---

### Task 7: Docs + final verification

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `docs/bdd-enforcement.md` (new section after "Interview tools", before "Enforcement summary")

- [ ] **Step 1: Update `docs/ROADMAP.md`**

1. Header: update the first line to
`Updated: 2026-06-07 (analysis tools delivered). Order = priority. ...`
(keep the rest of the sentence).

2. Append to the Delivered list:

```markdown
- **Analysis as state** — `analysis_submit` / `analysis_view` /
  `analysis_approve` / `analysis_discard`: for existing projects, Claude's
  codebase analysis persisted as a reviewable pipeline proposal (step list +
  Gherkin drafts in DB); approval materializes real steps + feature files;
  conditional gate blocks `step_add` while a proposal is open (schema v4)
```

3. Replace the whole `## Next` section (the `### 1. analyze_codebase` item)
by promoting workflow phases from Later, and renumber the hardening backlog:

```markdown
## Next

### 1. Workflow phases
Make `new_project` / `new_feature` / `generate_tests` real meta-phases
(interview → design → generate → execute) that produce concrete steps and
then disappear, as per the v2 design.

## Later

### 2. Hardening backlog (small, opportunistic)
```

(keep the existing hardening bullet list unchanged under it, and keep the
`## Non-goals (for now)` section as is).

- [ ] **Step 2: Update `docs/bdd-enforcement.md`**

Insert after the "Interview tools" section (after the audit-events paragraph,
line 124) and before "## Enforcement summary":

```markdown
## Analysis tools

For existing codebases, the analysis outcome is Bisset state: a pipeline
proposal (step list + Gherkin drafts) lives in the DB, freely revisable and
audited. Claude analyzes (driven by the `bisset/analyzer` prompt); Bisset
records. Bisset calls no LLM.

| Tool | What it does |
|------|--------------|
| `analysis_submit` | Opens (or replaces) the proposal: steps `{title, description?, feature_draft?}`. Drafts are syntax-checked here, so approval can never fail on Gherkin. Re-submitting an open proposal revises it; re-submitting a terminal one reopens it and re-arms the gate |
| `analysis_view` | Reads the persisted proposal (status + steps with drafts) |
| `analysis_approve` | Materializes the proposal: real steps appended after existing ones, drafts written to disk via the `set_feature` flow with order-prefixed filenames (no batch collisions; SHA registered). Requires no open interview |
| `analysis_discard` | Discards the open proposal; rows remain readable |

Gate: **conditional on existence**, like the interview. While a proposal is
`open`, `step_add` is rejected with an actionable error (approve or discard
first). Check order in `add_step`: interview first, then analysis. Approval
is non-atomic by declared design — a partial failure leaves a consistent
prefix of real steps and the proposal still open.

Resume: `session_status` and `session_resume` carry an `analysis` block with
`status`, `steps_proposed` / `features_drafted` counts and the proposed step
titles.

Audit: `analysis_submitted`, `analysis_revised`, `analysis_approved`,
`analysis_discarded` events in the session log.
```

- [ ] **Step 3: Mark the design doc as implemented**

In `docs/plans/2026-06-07-analyze-codebase-design.md`, change
`**Status:** Approved` to `**Status:** Implemented`.

- [ ] **Step 4: Commit**

```bash
git add docs/ROADMAP.md docs/bdd-enforcement.md docs/plans/2026-06-07-analyze-codebase-design.md
git commit -m "docs: analysis tools — bdd-enforcement section, roadmap update"
```

- [ ] **Step 5: Final verification (clean venv + demo)**

Run from the repo root, exactly:

```bash
PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q
./scripts/demo_bdd_gate.sh
```

Expected: **164 passed**, and the demo script exits 0 with its full
red → blocked → fix → green → accepted sequence. Both must succeed before
declaring the work done. If a fresh venv is requested for the final check:

```bash
python3 -m venv /tmp/bisset-verify-venv
/tmp/bisset-verify-venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. /tmp/bisset-verify-venv/bin/python3 -m pytest orchestrator/ -q
```
