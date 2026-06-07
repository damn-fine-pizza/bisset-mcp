# Interview Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `interview_question`, `interview_answer`, `interview_complete` so the requirements interview becomes persisted, resumable, audited Bisset state (design: `docs/plans/2026-06-07-interview-design.md`).

**Architecture:** Migration ladder refactor first (roadmap prerequisite for v3), then schema v3: `interview_status` column on `sessions` + new `interview_questions` table. One open question at a time; explicit completion; conditional gate in `engine.add_step` (active only while an interview is open). All logic in `engine.py`; thin endpoints in `app.py`; MCP exposure in `server.py`; interviewer prompt updated to drive the tools.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, pytest.

**Conventions (binding):**
- Run all tests with `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q` from the repo root.
- Branch: `dev/feature0013-interview` (already created, design doc committed).
- Baseline before Task 1: **98 passed**.
- NEVER add Co-Authored-By or AI-attribution trailers to commits or PR bodies.
- Subagents MUST NOT run `git checkout` / `git switch` (a reviewer once left the tree on main).

---

### Task 1: Migration ladder — stepwise version loop in `_migrate`

Refactor only; `SCHEMA_VERSION` stays 2. Fresh DBs get the **v1 base schema**
and then every ladder rung, so each migration path is exercised by every test
run (all `:memory:` DBs walk the ladder). Single source of truth: the base
schema never changes again; changes go in `_migrate_vN_to_vN+1` methods found
via `getattr`.

**Files:**
- Modify: `orchestrator/workflow_server/storage.py:74-184` (`_migrate`)
- Test: `orchestrator/workflow_server/tests/test_storage_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_storage_v2.py` (the file
already has a `db` fixture and imports `Storage`):

```python
def test_fresh_db_built_through_the_ladder():
    """A fresh DB gets the v1 base schema + every ladder rung."""
    from orchestrator.workflow_server.storage import SCHEMA_VERSION
    db = Storage(db_path=":memory:")
    ver = db.conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert ver == SCHEMA_VERSION
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(steps)").fetchall()]
    # added by the 1->2 rung, NOT by the base schema
    assert "feature_content" in cols
    assert "feature_hash" in cols
    db.close()


def test_migrate_idempotent_on_reopen(tmp_path):
    """Second open of an up-to-date DB: early return, no re-migration, no error."""
    from orchestrator.workflow_server.storage import SCHEMA_VERSION
    db_file = str(tmp_path / "ladder.db")
    db = Storage(db_path=db_file)
    db.close()
    db = Storage(db_path=db_file)
    ver = db.conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert ver == SCHEMA_VERSION
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_storage_v2.py -q`

Expected: `test_fresh_db_built_through_the_ladder` FAILS only if the current
base schema were missing the columns — it does include them, so **both new
tests may already pass against the old code**. That is fine: this task is a
refactor; the tests pin the contract the ladder must keep. Verify they pass,
then refactor and verify nothing breaks.

- [ ] **Step 3: Refactor `_migrate` into the ladder**

In `orchestrator/workflow_server/storage.py`, replace the whole `_migrate`
method (lines 74-184) with:

```python
    def _migrate(self):
        """Create or upgrade the schema via a stepwise migration ladder.

        Fresh databases get the v1 base schema and then every ladder rung
        (_migrate_v1_to_v2, _migrate_v2_to_v3, ...), so every migration path
        is exercised continuously. The base schema is frozen at v1: schema
        changes only ever go in new ladder rungs.
        """
        cur = self.conn.cursor()

        current = 0
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cur.fetchone():
            cur.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cur.fetchone()
            current = row[0] if row else 0
            if current >= SCHEMA_VERSION:
                # Sentinel check: a version number alone proves nothing — a DB
                # from a different application lineage may report any version.
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
                )
                if cur.fetchone():
                    return
                raise RuntimeError(
                    f"Database at {self.db_path} reports schema version "
                    f"{current} but has no 'projects' table — it belongs to a "
                    "different application lineage. Move the file aside or "
                    "point DATABASE_PATH to a fresh location."
                )

        if current == 0:
            self._create_base_schema_v1(cur)
            current = 1

        while current < SCHEMA_VERSION:
            getattr(self, f"_migrate_v{current}_to_v{current + 1}")(cur)
            current += 1

        cur.execute("DELETE FROM schema_version")
        cur.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )
        self.conn.commit()

    @staticmethod
    def _create_base_schema_v1(cur: sqlite3.Cursor) -> None:
        """The original v1 schema. Frozen: schema changes go in ladder rungs."""
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            test_runner TEXT NOT NULL DEFAULT 'generic',
            test_args TEXT NOT NULL DEFAULT '',
            adapter TEXT NOT NULL DEFAULT 'generic',
            features_dir TEXT NOT NULL DEFAULT 'features/',
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            workflow_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            default_rules TEXT,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS steps (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            "order" INTEGER NOT NULL,
            feature_path TEXT,
            gate TEXT NOT NULL DEFAULT 'tests_only',
            depends_on TEXT,
            rules_override TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            retries INTEGER NOT NULL DEFAULT 0,
            current_coverage REAL NOT NULL DEFAULT 0.0,
            gate_result TEXT,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS test_runs (
            id TEXT PRIMARY KEY,
            step_id TEXT NOT NULL REFERENCES steps(id),
            session_id TEXT NOT NULL REFERENCES sessions(id),
            run_at REAL NOT NULL,
            passed INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            coverage REAL NOT NULL DEFAULT 0.0,
            runner_output TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            event_type TEXT NOT NULL,
            step_id TEXT,
            data TEXT,
            timestamp REAL NOT NULL
        );
        """)

    @staticmethod
    def _migrate_v1_to_v2(cur: sqlite3.Cursor) -> None:
        """v1 -> v2: additive feature columns on steps (guarded: ALTER has no IF NOT EXISTS)."""
        existing = {r[1] for r in cur.execute("PRAGMA table_info(steps)").fetchall()}
        if "feature_content" not in existing:
            cur.execute("ALTER TABLE steps ADD COLUMN feature_content TEXT")
        if "feature_hash" not in existing:
            cur.execute("ALTER TABLE steps ADD COLUMN feature_hash TEXT")
```

Note: the old base schema contained `feature_content`/`feature_hash` inline
with a "keep in sync" comment — that duplication is exactly what the ladder
removes. The v1 base above does NOT have those columns; the 1→2 rung adds
them everywhere, including on fresh DBs.

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **100 passed** (98 + 2 new). The pre-existing
`test_migration_v1_to_v2_adds_feature_columns` and the foreign-lineage
sentinel test must still pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/storage.py orchestrator/workflow_server/tests/test_storage_v2.py
git commit -m "refactor(storage): stepwise migration ladder — prerequisite for schema v3"
```

---

### Task 2: Schema v3 — `interview_status` + `interview_questions`, storage CRUD

**Files:**
- Modify: `orchestrator/workflow_server/storage.py` (`SCHEMA_VERSION`, new rung, new CRUD section after the Session section)
- Test: `orchestrator/workflow_server/tests/test_storage_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_storage_v2.py`:

```python
def _build_v2_db(db_file):
    """A handmade v2 database (v1 schema + feature columns + version 2)."""
    import sqlite3
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (2);
        CREATE TABLE projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
            test_runner TEXT NOT NULL DEFAULT 'generic', test_args TEXT NOT NULL DEFAULT '',
            adapter TEXT NOT NULL DEFAULT 'generic', features_dir TEXT NOT NULL DEFAULT 'features/',
            created_at REAL NOT NULL);
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            workflow_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            default_rules TEXT, created_at REAL NOT NULL);
        CREATE TABLE steps (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
            title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            "order" INTEGER NOT NULL, feature_path TEXT,
            feature_content TEXT, feature_hash TEXT,
            gate TEXT NOT NULL DEFAULT 'tests_only', depends_on TEXT, rules_override TEXT,
            status TEXT NOT NULL DEFAULT 'pending', retries INTEGER NOT NULL DEFAULT 0,
            current_coverage REAL NOT NULL DEFAULT 0.0, gate_result TEXT, created_at REAL NOT NULL);
        CREATE TABLE test_runs (
            id TEXT PRIMARY KEY, step_id TEXT NOT NULL REFERENCES steps(id),
            session_id TEXT NOT NULL REFERENCES sessions(id), run_at REAL NOT NULL,
            passed INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
            coverage REAL NOT NULL DEFAULT 0.0, runner_output TEXT NOT NULL DEFAULT '');
        CREATE TABLE events (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
            event_type TEXT NOT NULL, step_id TEXT, data TEXT, timestamp REAL NOT NULL);
    """)
    conn.commit()
    conn.close()


def test_migration_v2_to_v3_adds_interview_state(tmp_path):
    from orchestrator.workflow_server.storage import SCHEMA_VERSION
    db_file = str(tmp_path / "v2.db")
    _build_v2_db(db_file)
    db = Storage(db_path=db_file)
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(sessions)").fetchall()]
    assert "interview_status" in cols
    tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "interview_questions" in tables
    ver = db.conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert ver == SCHEMA_VERSION
    db.close()


def test_interview_question_roundtrip(db):
    pid = db.create_project("myapp", "/tmp/iq-app", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("new_project")
    q1 = db.add_interview_question(sid, "What does the project do?")
    q2 = db.add_interview_question(sid, "Which constraints apply?")
    qs = db.list_interview_questions(sid)
    assert [q["order"] for q in qs] == [1, 2]
    assert [q["id"] for q in qs] == [q1, q2]
    assert all(q["status"] == "open" for q in qs)
    assert qs[0]["asked_at"] is not None
    # storage allows multiple open rows; the one-open invariant is engine-level
    assert db.get_open_interview_question(sid)["id"] == q1
    assert db.get_interview_question("nonexistent") is None


def test_answer_interview_question(db):
    pid = db.create_project("myapp", "/tmp/aq-app", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("new_project")
    qid = db.add_interview_question(sid, "What does it do?")
    db.answer_interview_question(qid, "It bakes pizzas")
    q = db.get_interview_question(qid)
    assert q["status"] == "answered"
    assert q["answer"] == "It bakes pizzas"
    assert q["answered_at"] is not None
    assert db.get_open_interview_question(sid) is None


def test_set_interview_status(db):
    pid = db.create_project("myapp", "/tmp/is-app", "pytest", "", "pytest", "features/")
    db.lock_project(pid)
    sid = db.create_session("new_project")
    assert db.get_session(sid)["interview_status"] is None
    db.set_interview_status(sid, "open")
    assert db.get_session(sid)["interview_status"] == "open"
    db.set_interview_status(sid, "complete")
    assert db.get_session(sid)["interview_status"] == "complete"
```

Also UPDATE the existing v1 migration test: in
`test_migration_v1_to_v2_adds_feature_columns`, the final assertion
`assert ver == 2` becomes version-agnostic and the test proves the full
ladder. Change its last block to:

```python
    db = Storage(db_path=db_file)
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(steps)").fetchall()]
    assert "feature_content" in cols
    assert "feature_hash" in cols
    from orchestrator.workflow_server.storage import SCHEMA_VERSION
    ver = db.conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert ver == SCHEMA_VERSION  # v1 walks the whole ladder, not just one rung
    scols = [r[1] for r in db.conn.execute("PRAGMA table_info(sessions)").fetchall()]
    assert "interview_status" in scols
    db.close()
```

(If the collaudo work renamed or restructured that test, apply the same
change to whichever test builds the v1 fixture and asserts the version.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_storage_v2.py -q`
Expected: 5 FAIL — `ver == SCHEMA_VERSION` asserts fail (still 2 → no v3 rung),
`AttributeError: 'Storage' object has no attribute 'add_interview_question'`,
missing `interview_status` column.

- [ ] **Step 3: Implement**

In `orchestrator/workflow_server/storage.py`:

(a) Line 8: `SCHEMA_VERSION = 3`

(b) Add right after `_migrate_v1_to_v2`:

```python
    @staticmethod
    def _migrate_v2_to_v3(cur: sqlite3.Cursor) -> None:
        """v2 -> v3: interview as session state (guarded: ALTER has no IF NOT EXISTS)."""
        existing = {r[1] for r in cur.execute("PRAGMA table_info(sessions)").fetchall()}
        if "interview_status" not in existing:
            cur.execute("ALTER TABLE sessions ADD COLUMN interview_status TEXT")
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS interview_questions (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            "order" INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            asked_at REAL NOT NULL,
            answered_at REAL
        );
        """)
```

(c) Add a new section between the Session section and the Step section
(i.e. right before the `# ── Step ──...` banner):

```python
    # ── Interview ─────────────────────────────────────────────────────────────

    def set_interview_status(self, session_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET interview_status=? WHERE id=?",
            (status, session_id),
        )
        self.conn.commit()

    def add_interview_question(self, session_id: str, question: str) -> str:
        """Insert an open question with the next order number."""
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
        self.conn.commit()
        return qid

    def get_interview_question(self, question_id: str) -> dict | None:
        return self._fetchone_dict(
            "SELECT * FROM interview_questions WHERE id=?", (question_id,)
        )

    def list_interview_questions(self, session_id: str) -> list[dict]:
        return self._fetchall_dict(
            'SELECT * FROM interview_questions WHERE session_id=? ORDER BY "order"',
            (session_id,),
        )

    def get_open_interview_question(self, session_id: str) -> dict | None:
        return self._fetchone_dict(
            "SELECT * FROM interview_questions WHERE session_id=? AND status='open' "
            'ORDER BY "order" LIMIT 1',
            (session_id,),
        )

    def answer_interview_question(self, question_id: str, answer: str) -> None:
        self.conn.execute(
            "UPDATE interview_questions SET answer=?, status='answered', "
            "answered_at=? WHERE id=?",
            (answer, time.time(), question_id),
        )
        self.conn.commit()
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **104 passed** (100 + 4 new; 1 existing test updated in place)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/storage.py orchestrator/workflow_server/tests/test_storage_v2.py
git commit -m "feat(storage): schema v3 — interview_status on sessions + interview_questions table"
```

---

### Task 3: `engine.interview_question` + `engine.interview_answer`

**Files:**
- Modify: `orchestrator/workflow_server/engine.py` (new section after `session_status`, before the `# -- Step --` banner)
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py` (the file has
an `engine` fixture; `pytest` is already imported):

```python
def test_interview_question_opens_interview(engine):
    pid = engine.create_project("myapp", "/tmp/iv1")
    sid = engine.start_session(pid, "new_project")
    r = engine.interview_question(sid, "What does the project do?")
    assert r["order"] == 1
    assert r["reopened"] is False
    assert engine.db.get_session(sid)["interview_status"] == "open"
    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "question_asked" for e in events)


def test_interview_question_rejects_second_open(engine):
    pid = engine.create_project("myapp", "/tmp/iv2")
    sid = engine.start_session(pid, "new_project")
    engine.interview_question(sid, "First?")
    with pytest.raises(ValueError, match="already open"):
        engine.interview_question(sid, "Second?")


def test_interview_question_rejects_empty(engine):
    pid = engine.create_project("myapp", "/tmp/iv3")
    sid = engine.start_session(pid, "new_project")
    with pytest.raises(ValueError, match="empty"):
        engine.interview_question(sid, "   ")


def test_interview_question_unknown_session(engine):
    with pytest.raises(ValueError, match="Session not found"):
        engine.interview_question("nope", "Q?")


def test_interview_answer_records_and_logs(engine):
    pid = engine.create_project("myapp", "/tmp/iv4")
    sid = engine.start_session(pid, "new_project")
    qid = engine.interview_question(sid, "What does it do?")["question_id"]
    r = engine.interview_answer(qid, "It bakes pizzas")
    assert r["revised"] is False
    q = engine.db.get_interview_question(qid)
    assert q["status"] == "answered"
    assert q["answer"] == "It bakes pizzas"
    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "answer_recorded" for e in events)


def test_interview_answer_revision(engine):
    pid = engine.create_project("myapp", "/tmp/iv5")
    sid = engine.start_session(pid, "new_project")
    qid = engine.interview_question(sid, "What does it do?")["question_id"]
    engine.interview_answer(qid, "First version")
    r = engine.interview_answer(qid, "Corrected version")
    assert r["revised"] is True
    assert engine.db.get_interview_question(qid)["answer"] == "Corrected version"
    types = [e["event_type"] for e in engine.db.list_events(sid)]
    assert "answer_recorded" in types
    assert "answer_revised" in types


def test_interview_answer_rejects_empty_and_unknown(engine):
    pid = engine.create_project("myapp", "/tmp/iv6")
    sid = engine.start_session(pid, "new_project")
    qid = engine.interview_question(sid, "Q?")["question_id"]
    with pytest.raises(ValueError, match="empty"):
        engine.interview_answer(qid, "  ")
    with pytest.raises(ValueError, match="not found"):
        engine.interview_answer("nonexistent", "answer")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -q`
Expected: 7 FAIL with `AttributeError: 'WorkflowEngine' object has no attribute 'interview_question'`

- [ ] **Step 3: Implement**

In `orchestrator/workflow_server/engine.py`, insert a new section after
`session_status` (right before the `# -- Step --...` banner):

```python
    # -- Interview ----------------------------------------------------------------

    def interview_question(self, session_id: str, question: str) -> dict:
        """Register an interview question (one open at a time; reopens if complete)."""
        question = (question or "").strip()
        if not question:
            raise ValueError("Question must not be empty")
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        open_q = self.db.get_open_interview_question(session_id)
        if open_q:
            raise ValueError(
                f"An interview question is already open: {open_q['question']!r} "
                f"(order {open_q['order']}). Record its answer via "
                "interview_answer before asking another."
            )
        reopened = session.get("interview_status") == "complete"
        qid = self.db.add_interview_question(session_id, question)
        self.db.set_interview_status(session_id, "open")
        if reopened:
            self.db.add_event(session_id, "interview_reopened",
                              data={"question_id": qid})
        q = self.db.get_interview_question(qid)
        self.db.add_event(session_id, "question_asked",
                          data={"question_id": qid, "order": q["order"],
                                "question": question})
        return {"question_id": qid, "order": q["order"], "reopened": reopened}

    def interview_answer(self, question_id: str, answer: str) -> dict:
        """Record (or revise) the answer to an interview question.

        Revising never changes interview_status: only interview_question
        reopens a completed interview.
        """
        answer = (answer or "").strip()
        if not answer:
            raise ValueError("Answer must not be empty")
        q = self.db.get_interview_question(question_id)
        if not q:
            raise ValueError(f"Interview question not found: {question_id}")
        revised = q["status"] == "answered"
        self.db.answer_interview_question(question_id, answer)
        self.db.add_event(q["session_id"],
                          "answer_revised" if revised else "answer_recorded",
                          data={"question_id": question_id, "order": q["order"]})
        return {"question_id": question_id, "order": q["order"],
                "revised": revised}
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **111 passed** (104 + 7)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/engine.py orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "feat(engine): interview_question + interview_answer — persisted Q&A with audit"
```

---

### Task 4: `engine.interview_complete`, gate in `add_step`, interview block in `session_status`

**Files:**
- Modify: `orchestrator/workflow_server/engine.py` (`session_status`, the Interview section from Task 3, `add_step`)
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py`:

```python
def test_interview_complete_happy_path(engine):
    pid = engine.create_project("myapp", "/tmp/ic1")
    sid = engine.start_session(pid, "new_project")
    qid = engine.interview_question(sid, "What does it do?")["question_id"]
    engine.interview_answer(qid, "It bakes pizzas")
    r = engine.interview_complete(sid)
    assert r == {"interview_status": "complete", "asked": 1, "answered": 1}
    assert engine.db.get_session(sid)["interview_status"] == "complete"
    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "interview_completed" for e in events)


def test_interview_complete_rejects_open_question(engine):
    pid = engine.create_project("myapp", "/tmp/ic2")
    sid = engine.start_session(pid, "new_project")
    engine.interview_question(sid, "Unanswered?")
    with pytest.raises(ValueError, match="still open"):
        engine.interview_complete(sid)


def test_interview_complete_rejects_never_started(engine):
    pid = engine.create_project("myapp", "/tmp/ic3")
    sid = engine.start_session(pid, "new_project")
    with pytest.raises(ValueError, match="No interview"):
        engine.interview_complete(sid)


def test_interview_complete_rejects_zero_answers(engine):
    """Defense in depth: 'open' with no questions is unreachable via the
    engine, but the invariant must hold even against direct DB state."""
    pid = engine.create_project("myapp", "/tmp/ic4")
    sid = engine.start_session(pid, "new_project")
    engine.db.set_interview_status(sid, "open")
    with pytest.raises(ValueError, match="no answers"):
        engine.interview_complete(sid)


def test_interview_reopen_after_complete(engine):
    pid = engine.create_project("myapp", "/tmp/ic5")
    sid = engine.start_session(pid, "new_project")
    qid = engine.interview_question(sid, "Q1?")["question_id"]
    engine.interview_answer(qid, "A1")
    engine.interview_complete(sid)
    r = engine.interview_question(sid, "One more thing?")
    assert r["reopened"] is True
    assert engine.db.get_session(sid)["interview_status"] == "open"
    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "interview_reopened" for e in events)
    # the gate is re-armed
    with pytest.raises(ValueError, match="Interview in progress"):
        engine.add_step(sid, "S1", "d", 1)


def test_add_step_gated_by_open_interview(engine):
    pid = engine.create_project("myapp", "/tmp/ic6")
    sid = engine.start_session(pid, "new_project")
    qid = engine.interview_question(sid, "What is the scope?")["question_id"]
    # gate active, error is actionable: carries the pending question
    with pytest.raises(ValueError, match="What is the scope"):
        engine.add_step(sid, "S1", "d", 1)
    engine.interview_answer(qid, "A small bakery API")
    # still gated: answered but not completed
    with pytest.raises(ValueError, match="interview_complete"):
        engine.add_step(sid, "S1", "d", 1)
    engine.interview_complete(sid)
    step_id = engine.add_step(sid, "S1", "d", 1)
    assert engine.db.get_step(step_id) is not None


def test_session_status_interview_block(engine):
    pid = engine.create_project("myapp", "/tmp/ic7")
    sid = engine.start_session(pid, "new_project")
    assert engine.session_status(sid)["interview"] is None
    qid = engine.interview_question(sid, "What does it do?")["question_id"]
    block = engine.session_status(sid)["interview"]
    assert block["status"] == "open"
    assert block["asked"] == 1
    assert block["answered"] == 0
    assert block["pending_question"]["question"] == "What does it do?"
    engine.interview_answer(qid, "Pizzas")
    engine.interview_complete(sid)
    block = engine.session_status(sid)["interview"]
    assert block["status"] == "complete"
    assert block["pending_question"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -q`
Expected: 7 FAIL (`no attribute 'interview_complete'`, gate not raising, missing `interview` key)

- [ ] **Step 3: Implement**

In `orchestrator/workflow_server/engine.py`:

(a) Append to the Interview section (after `interview_answer`):

```python
    def interview_complete(self, session_id: str) -> dict:
        """Declare the interview complete after invariant checks (gate opener)."""
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session.get("interview_status") is None:
            raise ValueError("No interview was started for this session.")
        open_q = self.db.get_open_interview_question(session_id)
        if open_q:
            raise ValueError(
                f"Cannot complete the interview: question {open_q['order']} "
                f"is still open: {open_q['question']!r}. Record its answer "
                "via interview_answer first."
            )
        questions = self.db.list_interview_questions(session_id)
        answered = sum(1 for q in questions if q["status"] == "answered")
        if answered == 0:
            raise ValueError(
                "Cannot complete the interview: no answers recorded. Ask at "
                "least one question via interview_question and record its "
                "answer."
            )
        self.db.set_interview_status(session_id, "complete")
        self.db.add_event(session_id, "interview_completed",
                          data={"asked": len(questions), "answered": answered})
        return {"interview_status": "complete",
                "asked": len(questions), "answered": answered}

    def _interview_block(self, session_id: str, session: dict) -> dict | None:
        """Interview summary for status responses (None = never started)."""
        status = session.get("interview_status")
        if status is None:
            return None
        questions = self.db.list_interview_questions(session_id)
        open_q = self.db.get_open_interview_question(session_id)
        pending = None
        if open_q:
            pending = {"id": open_q["id"], "order": open_q["order"],
                       "question": open_q["question"]}
        return {"status": status,
                "asked": len(questions),
                "answered": sum(1 for q in questions if q["status"] == "answered"),
                "pending_question": pending}
```

(b) In `session_status`, add the `interview` key to the returned dict:

```python
        return {
            "session": session,
            "steps": steps,
            "current_step": current,
            "total_steps": len(steps),
            "completed_steps": sum(1 for s in steps if s["status"] == "passed"),
            "failed_steps": sum(1 for s in steps if s["status"] == "failed"),
            "interview": self._interview_block(session_id, session) if session else None,
        }
```

(c) Replace `add_step` with the gated version:

```python
    def add_step(self, session_id: str, title: str, description: str, order: int,
                 **kwargs) -> str:
        """Add a step to a session (gated while an interview is open)."""
        session = self.db.get_session(session_id)
        if session and session.get("interview_status") == "open":
            open_q = self.db.get_open_interview_question(session_id)
            detail = (f" Open question ({open_q['order']}): {open_q['question']!r}."
                      if open_q else "")
            raise ValueError(
                "Interview in progress: answer the open question and call "
                "interview_complete before adding steps." + detail
            )
        step_id = self.db.add_step(session_id, title, description, order, **kwargs)
        self.db.add_event(session_id, "step_added", step_id=step_id, data={
            "title": title, "order": order,
        })
        return step_id
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **118 passed** (111 + 7). Sessions without an interview keep the
exact current `add_step` behaviour — every pre-existing test must stay green.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/engine.py orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "feat(engine): interview_complete + conditional step_add gate + interview in session_status"
```

---

### Task 5: HTTP endpoints + interview block in `session_resume`

**Files:**
- Modify: `orchestrator/workflow_server/app.py` (`session_resume` body; new Interview section after the Session endpoints, before the `# Pipeline / Steps` banner)
- Test: `orchestrator/workflow_server/tests/test_app_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_app_v2.py`. The file gained
a `_payload` helper with the gherkin work; if it is missing, define it first
exactly as:

```python
def _payload(response):
    """Extract payload dict from ResponseWrapper response."""
    return json.loads(response.json()["content"][0]["text"])
```

Then append:

```python
def _interview_session(client, path):
    r = client.post("/project_create", json={"name": "iv-app", "path": path})
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={"project_id": pid, "workflow_type": "new_project"})
    return pid, _payload(r)["session_id"]


def test_interview_flow_endpoints(client):
    pid, sid = _interview_session(client, "/tmp/iv-flow")

    r = client.post("/interview_question", json={
        "session_id": sid, "question": "What does the project do?",
    })
    body = _payload(r)
    qid = body["question_id"]
    assert body["order"] == 1

    # gate: step_add blocked while the interview is open
    r = client.post("/step_add", json={"session_id": sid, "title": "S1", "order": 1})
    assert r.json()["is_error"] is True
    assert "Interview in progress" in _payload(r)["error"]

    r = client.post("/interview_answer", json={"question_id": qid, "answer": "It bakes pizzas"})
    assert _payload(r)["revised"] is False

    r = client.post("/interview_complete", json={"session_id": sid})
    body = _payload(r)
    assert body == {"interview_status": "complete", "asked": 1, "answered": 1}

    # gate open: step_add now succeeds
    r = client.post("/step_add", json={"session_id": sid, "title": "S1", "order": 1})
    assert r.json()["is_error"] is False

    r = client.get(f"/session_status?session_id={sid}")
    assert _payload(r)["interview"]["status"] == "complete"


def test_interview_question_double_open_is_error(client):
    pid, sid = _interview_session(client, "/tmp/iv-double")
    client.post("/interview_question", json={"session_id": sid, "question": "First?"})
    r = client.post("/interview_question", json={"session_id": sid, "question": "Second?"})
    assert r.json()["is_error"] is True
    assert "already open" in _payload(r)["error"]


def test_session_resume_reports_pending_question(client):
    pid, sid = _interview_session(client, "/tmp/iv-resume")
    client.post("/interview_question", json={
        "session_id": sid, "question": "Which constraints apply?",
    })
    r = client.post("/session_resume", json={"project_id": pid})
    body = _payload(r)
    assert body["session_id"] == sid
    assert body["interview"]["status"] == "open"
    assert body["interview"]["pending_question"]["question"] == "Which constraints apply?"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_app_v2.py -q`
Expected: 3 FAIL (404 on `/interview_question`, missing `interview` key in resume payload)

- [ ] **Step 3: Implement**

In `orchestrator/workflow_server/app.py`:

(a) In the `session_resume` endpoint, replace the success path with:

```python
        sid = request.app.state.engine.resume_session(project_id)
        interview = request.app.state.engine.session_status(sid)["interview"]
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({"session_id": sid, "interview": interview}, duration)
```

(b) Insert a new section after the Session endpoints (before the
`# Pipeline / Steps` banner):

```python
# ============================================================================
# Interview
# ============================================================================

@app.post("/interview_question")
async def interview_question(request: Request) -> Dict[str, Any]:
    """Register an interview question (opens the interview; one open at a time)."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.interview_question(
            body["session_id"], body["question"])
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "INTERVIEW_QUESTION_ERROR", 500)


@app.post("/interview_answer")
async def interview_answer(request: Request) -> Dict[str, Any]:
    """Record (or revise) the user's answer to an interview question."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.interview_answer(
            body["question_id"], body["answer"])
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "INTERVIEW_ANSWER_ERROR", 500)


@app.post("/interview_complete")
async def interview_complete(request: Request) -> Dict[str, Any]:
    """Declare the interview complete; unblocks step_add."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.interview_complete(body["session_id"])
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "INTERVIEW_COMPLETE_ERROR", 500)
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **121 passed** (118 + 3). The `session_resume` payload change is
additive (`session_id` untouched) — existing e2e tests must stay green.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/app.py orchestrator/workflow_server/tests/test_app_v2.py
git commit -m "feat(api): interview endpoints + pending question in session_resume"
```

---

### Task 6: MCP exposure

**Files:**
- Modify: `orchestrator/mcp_server/server.py` (`_build_tools`: new Interview entries after `session_list`, before the `# Pipeline` comment)
- Test: `orchestrator/mcp_server/tests/test_client_v2.py`

All three tools are writes (POST): NO change to `client.py`'s `_GET_TOOLS`.

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/mcp_server/tests/test_client_v2.py`:

```python
def test_interview_tools_exposed():
    from orchestrator.mcp_server.server import BissetMCPServer
    tools = {t["name"] for t in BissetMCPServer()._build_tools()}
    assert {"interview_question", "interview_answer", "interview_complete"} <= tools


def test_interview_tools_routing():
    from orchestrator.mcp_server.client import _GET_TOOLS
    # all three are writes: they must go through POST
    assert "interview_question" not in _GET_TOOLS
    assert "interview_answer" not in _GET_TOOLS
    assert "interview_complete" not in _GET_TOOLS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/mcp_server/tests/ -q`
Expected: 1 FAIL (`test_interview_tools_exposed`); `test_interview_tools_routing` passes already (nothing added to `_GET_TOOLS`) — keep it as a regression pin.

- [ ] **Step 3: Implement**

In `orchestrator/mcp_server/server.py` `_build_tools`, insert after the
`session_list` entry (before the `# Pipeline` comment):

```python
            # Interview
            {"name": "interview_question",
             "description": "Register an interview question Bisset-side before asking it (one open question at a time; reopens a completed interview)",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"}, "question": {"type": "string"},
             }, "required": ["session_id", "question"]}},
            {"name": "interview_answer",
             "description": "Record the user's answer to the open interview question (re-answering revises with audit)",
             "inputSchema": {"type": "object", "properties": {
                 "question_id": {"type": "string"}, "answer": {"type": "string"},
             }, "required": ["question_id", "answer"]}},
            {"name": "interview_complete",
             "description": "Declare the interview complete (requires no open question and at least one answer); unblocks step_add",
             "inputSchema": {"type": "object", "properties": {
                 "session_id": {"type": "string"},
             }, "required": ["session_id"]}},
```

Also update the `session_resume` tool description to:

```python
            {"name": "session_resume", "description": "Resume latest pausable session; reports interview state and pending question if any",
```

(Keep the existing schema style: every property fully typed — Copilot
compatibility was the reason for past fixes here.)

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **123 passed** (121 + 2)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/mcp_server/server.py orchestrator/mcp_server/tests/test_client_v2.py
git commit -m "feat(mcp): expose interview tools over MCP"
```

---

### Task 7: Interviewer prompt drives the tools

**Files:**
- Modify: `orchestrator/mcp_server/prompts.py:46-65` (`bisset/interviewer` template)
- Test: `orchestrator/mcp_server/tests/test_prompts_v2.py`

- [ ] **Step 1: Write the failing test**

Append to `orchestrator/mcp_server/tests/test_prompts_v2.py` (reuse the file's
existing import of `PromptRegistry`; add it if absent:
`from orchestrator.mcp_server.prompts import PromptRegistry`):

```python
def test_interviewer_prompt_mentions_interview_tools():
    reg = PromptRegistry()
    text = reg.render("bisset/interviewer", {}, {})
    for tool in ("interview_question", "interview_answer", "interview_complete"):
        assert tool in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/mcp_server/tests/test_prompts_v2.py -q`
Expected: 1 FAIL (tool names absent from the template)

- [ ] **Step 3: Implement**

In `orchestrator/mcp_server/prompts.py`, replace the `bisset/interviewer`
template registration with:

```python
        self._prompts["bisset/interviewer"] = PromptTemplate(
            "bisset/interviewer",
            """You are conducting a structured interview to define a development pipeline.

Project: {{project.name}}
Path: {{project.path}}

Your role:
- Ask one question at a time about the project scope, features, constraints, and success criteria
- Record every exchange in Bisset: register each question with interview_question BEFORE asking it, then record the user's reply with interview_answer
- On resume, check session_status: if a question is pending, re-ask it instead of starting over
- Build understanding of what needs to be built
- Identify testable acceptance criteria for each feature
- When the requirements are clear, call interview_complete, then produce a structured list of pipeline steps with Gherkin scenarios

Directory structure:
{{context.directory_structure}}

Relevant patterns:
{{context.patterns}}
"""
        )
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **124 passed** (123 + 1)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/mcp_server/prompts.py orchestrator/mcp_server/tests/test_prompts_v2.py
git commit -m "feat(prompts): interviewer prompt drives the interview tools"
```

---

### Task 8: Documentation

**Files:**
- Modify: `docs/bdd-enforcement.md` (new section after the Gherkin tools section)
- Modify: `docs/ROADMAP.md` (move item 1 from Next to Delivered)

- [ ] **Step 1: Document the interview tools in `docs/bdd-enforcement.md`**

Add after the "Gherkin tools" section:

```markdown
## Interview tools

The requirements interview is Bisset state: questions and answers live in the
DB, survive session ends, and are fully audited. Claude asks (driven by the
`bisset/interviewer` prompt); Bisset records. Bisset calls no LLM.

| Tool | What it does |
|------|--------------|
| `interview_question` | Registers the question and opens it (one open question at a time). On a completed interview: reopens it and re-arms the gate |
| `interview_answer` | Records the user's answer, closing the question. Re-answering revises with an `answer_revised` audit event |
| `interview_complete` | Declares the interview complete. Invariants: no open question, at least one answer. Unblocks `step_add` |

Gate: **conditional on existence**. Sessions that never start an interview
behave exactly as before. Once a question is registered, `step_add` is
rejected (with the pending question in the error) until `interview_complete`
passes — if you start the interview, you finish it.

Resume: `session_status` and `session_resume` carry an `interview` block with
`status`, `asked`/`answered` counts and the `pending_question`, so the agent
can pick up the thread mid-interview.

Audit: `question_asked`, `answer_recorded`, `answer_revised`,
`interview_completed`, `interview_reopened` events in the session log.
```

- [ ] **Step 2: Update `docs/ROADMAP.md`**

In the Delivered section, append:

```markdown
- **Interview as state** — `interview_question` / `interview_answer` /
  `interview_complete`: the requirements dialogue persisted per session,
  resumable mid-question, audited in `event_log`; conditional gate blocks
  `step_add` while an interview is open; stepwise migration ladder (schema v3)
```

Remove the whole "### 1. `interview_answer` — interview as Bisset state"
subsection from Next, renumber the remaining items (`analyze_codebase` → 1,
"Workflow phases" → 2, "Hardening backlog" → 3), and delete the now-done
"schema migration ladder" bullet from the hardening backlog. Update the
`Updated:` date at the top.

- [ ] **Step 3: Commit**

```bash
git add docs/bdd-enforcement.md docs/ROADMAP.md
git commit -m "docs: interview tools — bdd-enforcement section, roadmap update"
```

---

### Task 9: E2E extension

**Files:**
- Test: `orchestrator/tests/test_e2e.py`

- [ ] **Step 1: Write the e2e test (goes green immediately — integration check, not TDD)**

Append to `orchestrator/tests/test_e2e.py` (the file has `client` fixture and
`_payload` helper):

```python
def test_interview_lifecycle(client):
    """question -> gate blocks step_add -> answer -> complete -> step_add ok
    -> audit trail -> resume reports the interview."""
    r = client.post("/project_create", json={
        "name": "interview-e2e", "path": "/tmp/interview-e2e",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={
        "project_id": pid, "workflow_type": "new_project",
    })
    sid = _payload(r)["session_id"]

    # 1. Claude registers the question before asking it
    r = client.post("/interview_question", json={
        "session_id": sid, "question": "What does the project do?",
    })
    qid = _payload(r)["question_id"]

    # 2. The gate blocks step generation mid-interview
    r = client.post("/step_add", json={"session_id": sid, "title": "S1", "order": 1})
    assert r.json()["is_error"] is True
    assert "What does the project do?" in _payload(r)["error"]

    # 3. Resume mid-interview: the pending question comes back
    r = client.post("/session_resume", json={"project_id": pid})
    body = _payload(r)
    assert body["session_id"] == sid
    assert body["interview"]["pending_question"]["id"] == qid

    # 4. Answer + complete
    r = client.post("/interview_answer", json={
        "question_id": qid, "answer": "A pizza ordering API",
    })
    assert _payload(r)["revised"] is False
    r = client.post("/interview_complete", json={"session_id": sid})
    assert _payload(r)["asked"] == 1

    # 5. Gate open
    r = client.post("/step_add", json={"session_id": sid, "title": "S1", "order": 1})
    assert r.json()["is_error"] is False

    # 6. Full audit trail
    r = client.get(f"/event_log?session_id={sid}")
    types = {e["event_type"] for e in _payload(r)["events"]}
    assert {"question_asked", "answer_recorded", "interview_completed"} <= types
```

- [ ] **Step 2: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **125 passed** (124 + 1)

- [ ] **Step 3: Commit**

```bash
git add orchestrator/tests/test_e2e.py
git commit -m "test(e2e): interview lifecycle — gate, resume mid-question, audit trail"
```

---

### Task 10: Final verification + PR

- [ ] **Step 1: Full suite from a clean venv**

```bash
python3 -m venv /tmp/interview-verify-venv
/tmp/interview-verify-venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. /tmp/interview-verify-venv/bin/python3 -m pytest orchestrator/ -q
rm -rf /tmp/interview-verify-venv
```
Expected: **125 passed**

- [ ] **Step 2: Demo still green (no-interview sessions untouched)**

Run: `./scripts/demo_bdd_gate.sh`
Expected: `DEMO PASSED`, exit 0

- [ ] **Step 3: Update design doc status**

In `docs/plans/2026-06-07-interview-design.md` change `**Status:** Approved`
to `**Status:** Implemented`. Commit:

```bash
git add docs/plans/2026-06-07-interview-design.md
git commit -m "docs: mark interview design as implemented"
```

- [ ] **Step 4: Push and open PR (GitHub is the CI reference)**

```bash
git push -u origin dev/feature0013-interview
gh pr create --repo damn-fine-pizza/bisset-mcp \
  --head dev/feature0013-interview --base main \
  --title "feat: interview tools — interview_question / interview_answer / interview_complete" \
  --body "Implements the approved design (docs/plans/2026-06-07-interview-design.md): the requirements interview as persisted, resumable, audited Bisset state. Stepwise migration ladder + schema v3 (interview_status on sessions, interview_questions table). One open question at a time; explicit completion; conditional gate on step_add (active only once an interview starts — demo/CI flows untouched). Pending question surfaced by session_status and session_resume."
```

NOTE: never add Co-Authored-By or AI-attribution trailers to commits or PR bodies (user preference).

- [ ] **Step 5: Watch CI to green**

```bash
gh run list --repo damn-fine-pizza/bisset-mcp --branch dev/feature0013-interview --limit 1
```
Expected: `completed success` (both jobs: test + demo)
