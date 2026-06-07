# Gherkin Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `step_set_feature`, `step_get_feature`, `step_validate_feature` so the agent hands Gherkin to Bisset instead of writing files by hand (design: `docs/plans/2026-06-04-gherkin-tools-design.md`).

**Architecture:** Disk = truth, DB = registry (content + SHA-256 on the `steps` table, additive migration to schema v2). Drift detection on read and on test run. Validation via `behave --dry-run`. All logic in `engine.py`; thin endpoints in `app.py`; MCP exposure in `server.py`.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, behave (target-project side), pytest.

**Verified behave 1.3.3 facts (probed live — do not re-derive):**
1. `--format json` output is wrapped: `USING RUNNER:` banner before the array, text summary after it.
2. With undefined steps and snippets enabled, behave **injects snippet text inside the JSON array** → invalid JSON. Always pass `--no-snippets` when parsing JSON.
3. In dry-run JSON, `match` objects are misaligned when a step is undefined → **never** detect undefined steps from per-step JSON. Use the text summary (`N undefined`) for the count and the snippet block of a second plain run for the exact step names (`@given(u'...')` lines).
4. A scenario containing an undefined step has element `status: "error"` in dry-run; healthy scenarios are `"untested"`.

**Conventions:** run all tests with `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q` from the repo root. Branch: `dev/feature0010-gherkin-tools` (already created, design doc committed).

---

### Task 1: Storage schema v2 — `feature_content` + `feature_hash`

**Files:**
- Modify: `orchestrator/workflow_server/storage.py` (lines 8, 74-156, 313-328)
- Test: `orchestrator/workflow_server/tests/test_storage_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_storage_v2.py`:

```python
def test_step_feature_content_and_hash_roundtrip():
    db = Storage(db_path=":memory:")
    pid = db.create_project(name="p", path="/tmp/p")
    db.lock_project(pid)
    sid = db.create_session("new_feature")
    step_id = db.add_step(sid, "S1", "d", 1)
    db.update_step(step_id, feature_content="Feature: X\n", feature_hash="abc123")
    step = db.get_step(step_id)
    assert step["feature_content"] == "Feature: X\n"
    assert step["feature_hash"] == "abc123"
    db.close()


def test_migration_v1_to_v2_adds_feature_columns(tmp_path):
    """A v1 database opened by the new Storage gains the new columns."""
    import sqlite3
    db_file = str(tmp_path / "old.db")
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (1);
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

    db = Storage(db_path=db_file)
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(steps)").fetchall()]
    assert "feature_content" in cols
    assert "feature_hash" in cols
    ver = db.conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert ver == 2
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_storage_v2.py -q`
Expected: 2 FAIL (`Unknown step field: feature_content` and missing-column assert)

- [ ] **Step 3: Implement the migration**

In `orchestrator/workflow_server/storage.py`:

(a) line 8: `SCHEMA_VERSION = 2`

(b) Replace the body of `_migrate` (keep the method name and docstring style):

```python
    def _migrate(self):
        """Create or upgrade the schema (v2 adds feature_content/feature_hash)."""
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
                return

        if current == 1:
            # v1 -> v2: additive columns on steps
            cur.execute("ALTER TABLE steps ADD COLUMN feature_content TEXT")
            cur.execute("ALTER TABLE steps ADD COLUMN feature_hash TEXT")
        else:
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
                feature_content TEXT,
                feature_hash TEXT,
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

        cur.execute("DELETE FROM schema_version")
        cur.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )
        self.conn.commit()
```

(c) In `update_step` (line ~316) add to the `allowed` set:

```python
            "feature_content",
            "feature_hash",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: all pass (58 = 56 + 2 new)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/storage.py orchestrator/workflow_server/tests/test_storage_v2.py
git commit -m "feat(storage): schema v2 — feature_content + feature_hash on steps"
```

---

### Task 2: Gherkin helpers module

**Files:**
- Create: `orchestrator/workflow_server/gherkin.py`
- Create: `orchestrator/workflow_server/tests/test_gherkin.py`

- [ ] **Step 1: Write the failing tests**

Create `orchestrator/workflow_server/tests/test_gherkin.py`:

```python
"""Tests for Gherkin helpers: filename derivation and structural syntax check."""
import pytest
from orchestrator.workflow_server.gherkin import (
    derive_filename, sanitize_filename, check_syntax
)


def test_derive_filename_slugifies_title():
    assert derive_filename("Implement calculator") == "implement-calculator.feature"
    assert derive_filename("  Càlc!! v2  ") == "c-lc-v2.feature"
    assert derive_filename("***") == "feature.feature"


def test_sanitize_filename_accepts_simple_names():
    assert sanitize_filename("calc.feature") == "calc.feature"
    assert sanitize_filename("calc") == "calc.feature"


@pytest.mark.parametrize("bad", [
    "../evil.feature", "a/b.feature", "a\\b.feature", ".hidden", "/abs.feature",
])
def test_sanitize_filename_rejects_traversal(bad):
    with pytest.raises(ValueError):
        sanitize_filename(bad)


VALID = """Feature: Calculator
  Scenario: Add
    Given the numbers 1 and 2
    When I add them
    Then the result is 3
"""


def test_check_syntax_valid():
    assert check_syntax(VALID) == []


def test_check_syntax_missing_feature_header():
    errors = check_syntax("Scenario: X\n  Given y\n")
    assert any("Feature:" in e for e in errors)


def test_check_syntax_no_scenarios():
    errors = check_syntax("Feature: X\n")
    assert any("Scenario" in e for e in errors)


def test_check_syntax_scenario_without_steps():
    content = "Feature: X\n  Scenario: empty\n  Scenario: ok\n    Given z\n"
    errors = check_syntax(content)
    assert any("empty" in e for e in errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_gherkin.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator.workflow_server.gherkin'`

- [ ] **Step 3: Implement the module**

Create `orchestrator/workflow_server/gherkin.py`:

```python
"""Gherkin helpers — feature filename handling and structural syntax check.

check_syntax() is a lightweight structural validation used by
step_set_feature to refuse writing obvious garbage to disk. Full grammar
and step-definition validation is step_validate_feature's job (behave
--dry-run).
"""
import re

_SLUG_RE = re.compile(r'[^a-z0-9]+')
_STEP_KEYWORDS = ("Given ", "When ", "Then ", "And ", "But ", "* ")
_SCENARIO_KEYWORDS = ("Scenario:", "Scenario Outline:")


def derive_filename(title: str) -> str:
    """Derive a safe .feature filename from a step title."""
    slug = _SLUG_RE.sub('-', title.lower()).strip('-') or "feature"
    return f"{slug}.feature"


def sanitize_filename(filename: str) -> str:
    """Reject path traversal and force the .feature extension."""
    name = filename.strip()
    if (not name or '/' in name or '\\' in name
            or name.startswith('.') or '..' in name):
        raise ValueError(f"Invalid feature filename: {filename!r}")
    if not name.endswith(".feature"):
        name += ".feature"
    return name


def check_syntax(content: str) -> list[str]:
    """Structural validation. Returns a list of errors (empty = ok)."""
    errors: list[str] = []
    lines = [ln.strip() for ln in content.splitlines()]
    meaningful = [ln for ln in lines if ln and not ln.startswith('#')]

    if not any(ln.startswith("Feature:") for ln in meaningful):
        errors.append("Missing 'Feature:' header")

    scenarios: list[tuple[str, int]] = []  # (name, step_count)
    current: str | None = None
    steps = 0
    for ln in meaningful:
        if ln.startswith(_SCENARIO_KEYWORDS):
            if current is not None:
                scenarios.append((current, steps))
            current = ln.split(":", 1)[1].strip() or "<unnamed>"
            steps = 0
        elif current is not None and ln.startswith(_STEP_KEYWORDS):
            steps += 1
    if current is not None:
        scenarios.append((current, steps))

    if not scenarios:
        errors.append("No 'Scenario:' found")
    for name, count in scenarios:
        if count == 0:
            errors.append(f"Scenario '{name}' has no steps")
    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_gherkin.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/gherkin.py orchestrator/workflow_server/tests/test_gherkin.py
git commit -m "feat: gherkin helpers — filename derivation, sanitization, structural syntax check"
```

---

### Task 3: `engine.set_feature`

**Files:**
- Modify: `orchestrator/workflow_server/engine.py` (imports + new method after `current_step`, ~line 88)
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py`:

```python
VALID_FEATURE = """Feature: Calculator
  Scenario: Add
    Given the numbers 1 and 2
    When I add them
    Then the result is 3
"""


def test_set_feature_writes_file_and_registers(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Implement calculator", "d", 1)

    result = engine.set_feature(step_id, sid, VALID_FEATURE)
    assert result["written"] is True
    assert result["feature_path"] == "features/implement-calculator.feature"

    written = (tmp_path / "features" / "implement-calculator.feature").read_text()
    assert written == VALID_FEATURE

    step = engine.db.get_step(step_id)
    assert step["feature_path"] == "features/implement-calculator.feature"
    assert step["feature_content"] == VALID_FEATURE
    assert len(step["feature_hash"]) == 64  # sha256 hex

    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "feature_set" for e in events)


def test_set_feature_rejects_bad_syntax_without_writing(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Bad", "d", 1)

    result = engine.set_feature(step_id, sid, "this is not gherkin at all")
    assert result["written"] is False
    assert result["errors"]
    assert not (tmp_path / "features").exists()
    assert engine.db.get_step(step_id)["feature_content"] is None


def test_set_feature_rejects_traversal_filename(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "S", "d", 1)
    with pytest.raises(ValueError):
        engine.set_feature(step_id, sid, VALID_FEATURE, filename="../evil")
```

(`Storage.list_events(session_id, limit=100)` exists at `storage.py:432` — verified.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -q`
Expected: 3 FAIL with `AttributeError: 'WorkflowEngine' object has no attribute 'set_feature'`

- [ ] **Step 3: Implement**

In `orchestrator/workflow_server/engine.py` — add imports at the top:

```python
import hashlib
import os

from .gherkin import derive_filename, sanitize_filename, check_syntax
```

Add after `current_step` (before the `# -- Test Execution ---` section):

```python
    # -- Gherkin ------------------------------------------------------------------

    def _feature_paths(self, step: dict, project: dict) -> tuple[str, str]:
        """Return (rel_path, abs_path) for a step's feature file."""
        rel = step["feature_path"]
        return rel, os.path.join(project["path"], rel)

    def set_feature(self, step_id: str, session_id: str, content: str,
                    filename: str | None = None) -> dict:
        """Validate, write to disk (disk = truth) and register content + hash."""
        step = self.db.get_step(step_id)
        if not step:
            raise ValueError(f"Step not found: {step_id}")
        errors = check_syntax(content)
        if errors:
            return {"written": False, "errors": errors}

        session = self.db.get_session(session_id)
        project = self.db.get_project(session["project_id"])
        name = sanitize_filename(filename) if filename else derive_filename(step["title"])
        features_dir = project.get("features_dir", "features/").strip("/")
        rel_path = f"{features_dir}/{name}"
        abs_path = os.path.join(project["path"], rel_path)

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as fh:
            fh.write(content)

        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.db.update_step(step_id, feature_path=rel_path,
                            feature_content=content, feature_hash=digest)
        self.db.add_event(session_id, "feature_set", step_id=step_id,
                          data={"feature_path": rel_path, "hash": digest})
        return {"written": True, "feature_path": rel_path,
                "hash": digest, "errors": []}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/engine.py orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "feat(engine): set_feature — validate, write to disk, register content + hash"
```

---

### Task 4: `engine.get_feature` with drift detection

**Files:**
- Modify: `orchestrator/workflow_server/engine.py`
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py`:

```python
def test_get_feature_no_drift(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    engine.set_feature(step_id, sid, VALID_FEATURE)

    result = engine.get_feature(step_id, sid)
    assert result["content"] == VALID_FEATURE
    assert result["feature_drifted"] is False
    assert result["file_missing"] is False


def test_get_feature_detects_drift_and_realigns(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    engine.set_feature(step_id, sid, VALID_FEATURE)

    edited = VALID_FEATURE + "\n  Scenario: Human added\n    Given x\n"
    (tmp_path / "features" / "calc.feature").write_text(edited)

    result = engine.get_feature(step_id, sid)
    assert result["feature_drifted"] is True
    assert result["content"] == edited
    # DB copy realigned, event logged
    assert engine.db.get_step(step_id)["feature_content"] == edited
    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "feature_drift" for e in events)
    # Second read: no longer drifted
    assert engine.get_feature(step_id, sid)["feature_drifted"] is False


def test_get_feature_file_missing_returns_db_copy(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path), adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    engine.set_feature(step_id, sid, VALID_FEATURE)
    (tmp_path / "features" / "calc.feature").unlink()

    result = engine.get_feature(step_id, sid)
    assert result["file_missing"] is True
    assert result["content"] == VALID_FEATURE  # last DB copy as reference
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -q`
Expected: 3 FAIL with `AttributeError: ... no attribute 'get_feature'`

- [ ] **Step 3: Implement**

Add to `engine.py` right after `set_feature`:

```python
    def _detect_drift(self, step: dict, session_id: str, abs_path: str) -> tuple[str, bool]:
        """Read disk content and realign the DB copy if it drifted.

        Returns (disk_content, drifted). Caller must ensure the file exists.
        """
        with open(abs_path, "r", encoding="utf-8") as fh:
            disk_content = fh.read()
        disk_hash = hashlib.sha256(disk_content.encode("utf-8")).hexdigest()
        drifted = bool(step.get("feature_hash")) and disk_hash != step["feature_hash"]
        if drifted:
            self.db.update_step(step["id"], feature_content=disk_content,
                                feature_hash=disk_hash)
            self.db.add_event(session_id, "feature_drift", step_id=step["id"],
                              data={"feature_path": step["feature_path"],
                                    "new_hash": disk_hash})
        return disk_content, drifted

    def get_feature(self, step_id: str, session_id: str) -> dict:
        """Read the step's feature from disk (truth), reporting drift/missing."""
        step = self.db.get_step(step_id)
        if not step:
            raise ValueError(f"Step not found: {step_id}")
        if not step.get("feature_path"):
            raise ValueError(f"Step has no feature_path: {step_id}")
        session = self.db.get_session(session_id)
        project = self.db.get_project(session["project_id"])
        rel_path, abs_path = self._feature_paths(step, project)

        if not os.path.isfile(abs_path):
            return {"content": step.get("feature_content"),
                    "feature_path": rel_path,
                    "feature_drifted": False, "file_missing": True}

        content, drifted = self._detect_drift(step, session_id, abs_path)
        return {"content": content, "feature_path": rel_path,
                "feature_drifted": drifted, "file_missing": False}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/engine.py orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "feat(engine): get_feature — disk is truth, drift detected and realigned"
```

---

### Task 5: Drift detection in `run_tests`

**Files:**
- Modify: `orchestrator/workflow_server/engine.py:100-124` (`run_tests`)
- Modify: `orchestrator/workflow_server/app.py:259-276` (`step_run_tests` endpoint)
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

`run_tests` changes signature: it now returns `(AdapterResult, feature_drifted: bool)`.
The only production caller is the `step_run_tests` endpoint in `app.py` (verify with
`grep -rn 'run_tests' orchestrator/ --include='*.py'` before assuming).

- [ ] **Step 1: Write the failing test**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py`:

```python
def test_run_tests_reports_drift(engine, tmp_path):
    """run_tests flags drift when the file changed after set_feature.

    Uses the 'generic' runner with /bin/true so no real test framework runs.
    """
    pid = engine.create_project("myapp", str(tmp_path),
                                test_runner="true", adapter="generic")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    engine.set_feature(step_id, sid, VALID_FEATURE)

    (tmp_path / "features" / "calc.feature").write_text(VALID_FEATURE + "# edited\n")

    result, drifted = engine.run_tests(step_id, sid)
    assert drifted is True
    assert result.passed == 1  # /bin/true exit 0 -> generic adapter pass

    # second run: realigned, no drift
    result, drifted = engine.run_tests(step_id, sid)
    assert drifted is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py::test_run_tests_reports_drift -q`
Expected: FAIL (`cannot unpack non-sequence AdapterResult` or similar)

- [ ] **Step 3: Implement**

In `engine.py`, replace `run_tests` with:

```python
    def run_tests(self, step_id: str, session_id: str) -> tuple[AdapterResult, bool]:
        """Execute tests for a step via subprocess.

        Returns (result, feature_drifted). Disk is truth: a drifted feature
        still runs, but the drift is recorded and reported.
        """
        step = self.db.get_step(step_id)
        if not step or not step.get("feature_path"):
            return AdapterResult(passed=0, failed=0), False

        session = self.db.get_session(session_id)
        project = self.db.get_project(session["project_id"])

        drifted = False
        _, abs_path = self._feature_paths(step, project)
        if os.path.isfile(abs_path) and step.get("feature_hash"):
            _, drifted = self._detect_drift(step, session_id, abs_path)

        adapter = get_adapter(project.get("adapter", "generic"))
        cmd = [project["test_runner"]]
        if project.get("test_args"):
            cmd.extend(project["test_args"].split())
        cmd.append(step["feature_path"])

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                  cwd=project["path"])
            result = adapter.parse(proc.returncode, proc.stdout, proc.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            result = AdapterResult(passed=0, failed=1, errors=[str(e)])

        self.record_test_run(step_id, session_id, result.passed, result.failed,
                             result.coverage, result.raw_output)
        return result, drifted
```

In `app.py`, update the `step_run_tests` endpoint body:

```python
        result, drifted = request.app.state.engine.run_tests(step_id, session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success({
            "passed": result.passed,
            "failed": result.failed,
            "coverage": result.coverage,
            "errors": result.errors,
            "feature_drifted": drifted,
        }, duration)
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: all pass (if another caller of `run_tests` breaks, update it to unpack the tuple)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/engine.py orchestrator/workflow_server/app.py orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "feat(engine): run_tests detects and reports feature drift"
```

---

### Task 6: `engine.validate_feature` (behave dry-run)

**Files:**
- Modify: `orchestrator/workflow_server/engine.py`
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

Strategy (from the verified behave facts in the header):
1. Run `{runner} --dry-run --no-snippets --format json {feature_path}`.
2. `syntax_ok` = a JSON array is extractable from stdout. On failure, errors = stripped output.
3. `undefined count` = regex `(\d+)\s+undefined` on the text after the JSON.
4. If count > 0, second run `{runner} --dry-run {feature_path}` (snippets ON, no JSON) and extract step names from `@given(u'...')`-style snippet lines.

These tests use the real behave binary from the repo venv: they build a tiny
behave project in `tmp_path`. `BEHAVE` resolves to `<repo>/.venv/bin/behave`.

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py`:

```python
import os as _os

BEHAVE = _os.path.join(_os.path.dirname(__file__), "..", "..", "..", ".venv", "bin", "behave")
BEHAVE = _os.path.abspath(BEHAVE)

STEPS_PY = '''
from behave import given, when, then

@given("the numbers {a:d} and {b:d}")
def step_given(ctx, a, b):
    ctx.a, ctx.b = a, b

@when("I add them")
def step_when(ctx):
    ctx.result = ctx.a + ctx.b

@then("the result is {expected:d}")
def step_then(ctx, expected):
    assert ctx.result == expected
'''


def _behave_project(engine, tmp_path):
    pid = engine.create_project("myapp", str(tmp_path),
                                test_runner=BEHAVE,
                                test_args="--format json --no-snippets",
                                adapter="behave")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Calc", "d", 1)
    steps_dir = tmp_path / "features" / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "calc_steps.py").write_text(STEPS_PY)
    return sid, step_id


@pytest.mark.skipif(not _os.path.exists(BEHAVE), reason="behave not installed in .venv")
def test_validate_feature_all_defined(engine, tmp_path):
    sid, step_id = _behave_project(engine, tmp_path)
    engine.set_feature(step_id, sid, VALID_FEATURE)
    v = engine.validate_feature(step_id, sid)
    assert v["syntax_ok"] is True
    assert v["steps_defined"] is True
    assert v["undefined_steps"] == []
    assert v["errors"] == []


@pytest.mark.skipif(not _os.path.exists(BEHAVE), reason="behave not installed in .venv")
def test_validate_feature_undefined_step(engine, tmp_path):
    sid, step_id = _behave_project(engine, tmp_path)
    feature = VALID_FEATURE + "\n  Scenario: Ghost\n    Given a step nobody wrote\n"
    engine.set_feature(step_id, sid, feature)
    v = engine.validate_feature(step_id, sid)
    assert v["syntax_ok"] is True
    assert v["steps_defined"] is False
    assert any("a step nobody wrote" in s for s in v["undefined_steps"])


@pytest.mark.skipif(not _os.path.exists(BEHAVE), reason="behave not installed in .venv")
def test_validate_feature_broken_gherkin(engine, tmp_path):
    sid, step_id = _behave_project(engine, tmp_path)
    # bypass set_feature's structural check: write broken file directly
    engine.set_feature(step_id, sid, VALID_FEATURE)
    (tmp_path / "features" / "calc.feature").write_text(
        "Feature: X\n  Scenario: bad\n    Given ok\n  Garbage line outside any step\n")
    v = engine.validate_feature(step_id, sid)
    # behave refuses to parse -> syntax_ok False, errors carry the parser output
    assert v["syntax_ok"] is False
    assert v["errors"]


def test_validate_feature_requires_behave_adapter(engine, tmp_path):
    pid = engine.create_project("p", str(tmp_path), adapter="pytest")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "S", "d", 1, feature_path="x.feature")
    with pytest.raises(ValueError):
        engine.validate_feature(step_id, sid)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -q -k validate_feature`
Expected: 4 FAIL with `AttributeError: ... no attribute 'validate_feature'`

NOTE: if `test_validate_feature_broken_gherkin` turns out to produce parseable
JSON in your behave version (i.e. behave tolerates that input), adapt the
broken fixture to a guaranteed parse error (e.g. `"Feature\nScenario\n@@@"`),
do NOT weaken the assertion.

- [ ] **Step 3: Implement**

Add to `engine.py` after `get_feature` (needs `import json` and `import re` at the top — `json` is already imported, add `re`):

```python
    _UNDEFINED_COUNT_RE = re.compile(r"(\d+)\s+undefined")
    _SNIPPET_STEP_RE = re.compile(r"@(?:given|when|then|step)\(u?['\"](.+?)['\"]\)")

    def validate_feature(self, step_id: str, session_id: str) -> dict:
        """Dry-run validation: syntax + step definitions, without executing.

        Verified against behave 1.3.3: snippets corrupt --format json output,
        so the JSON pass runs with --no-snippets and exact undefined step
        names come from a second plain dry-run's snippet block.
        """
        step = self.db.get_step(step_id)
        if not step:
            raise ValueError(f"Step not found: {step_id}")
        if not step.get("feature_path"):
            raise ValueError(f"Step has no feature_path: {step_id}")
        session = self.db.get_session(session_id)
        project = self.db.get_project(session["project_id"])
        if project.get("adapter") != "behave":
            raise ValueError("step_validate_feature requires the behave adapter")

        runner = project["test_runner"]
        cmd = [runner, "--dry-run", "--no-snippets", "--format", "json",
               step["feature_path"]]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=60, cwd=project["path"])
        except FileNotFoundError:
            raise ValueError(f"behave runner not found: {runner}")

        from .adapters import strip_ansi
        output = strip_ansi(proc.stdout + proc.stderr)

        try:
            start = proc.stdout.index('[')
            end = proc.stdout.rindex(']')
            json.loads(proc.stdout[start:end + 1])
        except (ValueError, json.JSONDecodeError):
            return {"syntax_ok": False, "steps_defined": False,
                    "undefined_steps": [], "errors": [output]}

        m = self._UNDEFINED_COUNT_RE.search(output)
        undefined_count = int(m.group(1)) if m else 0
        undefined_steps: list[str] = []
        if undefined_count:
            proc2 = subprocess.run([runner, "--dry-run", step["feature_path"]],
                                   capture_output=True, text=True,
                                   timeout=60, cwd=project["path"])
            snippet_out = strip_ansi(proc2.stdout + proc2.stderr)
            undefined_steps = list(dict.fromkeys(
                self._SNIPPET_STEP_RE.findall(snippet_out)))

        return {"syntax_ok": True,
                "steps_defined": undefined_count == 0,
                "undefined_steps": undefined_steps,
                "errors": []}
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/engine.py orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "feat(engine): validate_feature — behave dry-run, split syntax/steps verdicts"
```

---

### Task 7: HTTP endpoints

**Files:**
- Modify: `orchestrator/workflow_server/app.py` (after `step_current`, ~line 257)
- Test: `orchestrator/workflow_server/tests/test_app_v2.py`

Endpoint mapping: `step_set_feature` POST (write); `step_get_feature` and
`step_validate_feature` GET with query params (read pattern, like `step_current`).

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_app_v2.py`. The file has a
`client` fixture but NO payload helper (it inlines the unwrapping) — define
`_payload` as part of this addition:

```python
def _payload(response):
    """Extract payload dict from ResponseWrapper response."""
    return json.loads(response.json()["content"][0]["text"])


VALID_FEATURE = """Feature: Calculator
  Scenario: Add
    Given the numbers 1 and 2
    When I add them
    Then the result is 3
"""


def test_step_set_and_get_feature_endpoints(client, tmp_path):
    r = client.post("/project_create", json={
        "name": "gf-app", "path": str(tmp_path), "adapter": "behave",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={"project_id": pid, "workflow_type": "new_feature"})
    sid = _payload(r)["session_id"]
    r = client.post("/step_add", json={"session_id": sid, "title": "Calc", "order": 1})
    step_id = _payload(r)["step_id"]

    r = client.post("/step_set_feature", json={
        "step_id": step_id, "session_id": sid, "content": VALID_FEATURE,
    })
    assert r.status_code == 200
    body = _payload(r)
    assert body["written"] is True
    assert body["feature_path"] == "features/calc.feature"

    r = client.get(f"/step_get_feature?step_id={step_id}&session_id={sid}")
    body = _payload(r)
    assert body["content"] == VALID_FEATURE
    assert body["feature_drifted"] is False


def test_step_set_feature_rejects_bad_gherkin(client, tmp_path):
    r = client.post("/project_create", json={
        "name": "gf-bad", "path": str(tmp_path), "adapter": "behave",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={"project_id": pid, "workflow_type": "new_feature"})
    sid = _payload(r)["session_id"]
    r = client.post("/step_add", json={"session_id": sid, "title": "Bad", "order": 1})
    step_id = _payload(r)["step_id"]

    r = client.post("/step_set_feature", json={
        "step_id": step_id, "session_id": sid, "content": "garbage",
    })
    body = _payload(r)
    assert body["written"] is False
    assert body["errors"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_app_v2.py -q`
Expected: 2 FAIL with 404 on `/step_set_feature`

- [ ] **Step 3: Implement the endpoints**

Insert in `app.py` after the `step_current` endpoint:

```python
@app.post("/step_set_feature")
async def step_set_feature(request: Request) -> Dict[str, Any]:
    """Validate and persist a Gherkin feature for a step (disk = truth)."""
    start = time.time()
    try:
        body = await request.json()
        result = request.app.state.engine.set_feature(
            body["step_id"], body["session_id"], body["content"],
            filename=body.get("filename"),
        )
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_SET_FEATURE_ERROR", 500)


@app.get("/step_get_feature")
async def step_get_feature(request: Request, step_id: str, session_id: str) -> Dict[str, Any]:
    """Read a step's feature from disk, reporting drift and missing file."""
    start = time.time()
    try:
        result = request.app.state.engine.get_feature(step_id, session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_GET_FEATURE_ERROR", 500)


@app.get("/step_validate_feature")
async def step_validate_feature(request: Request, step_id: str, session_id: str) -> Dict[str, Any]:
    """Dry-run validation: Gherkin syntax + step definitions."""
    start = time.time()
    try:
        result = request.app.state.engine.validate_feature(step_id, session_id)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_VALIDATE_FEATURE_ERROR", 500)
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/app.py orchestrator/workflow_server/tests/test_app_v2.py
git commit -m "feat(api): endpoints for step_set_feature / step_get_feature / step_validate_feature"
```

---

### Task 8: MCP exposure

**Files:**
- Modify: `orchestrator/mcp_server/server.py` (`_build_tools`, after the `step_current` entry ~line 75)
- Modify: `orchestrator/mcp_server/client.py:15-25` (`_GET_TOOLS`)
- Test: `orchestrator/mcp_server/tests/test_client_v2.py`

- [ ] **Step 1: Write the failing test**

Append to `orchestrator/mcp_server/tests/test_client_v2.py` (reuse the file's
existing import style):

```python
def test_gherkin_tools_routing():
    from orchestrator.mcp_server.client import _GET_TOOLS
    # reads go through GET, the write goes through POST
    assert "step_get_feature" in _GET_TOOLS
    assert "step_validate_feature" in _GET_TOOLS
    assert "step_set_feature" not in _GET_TOOLS


def test_gherkin_tools_exposed():
    from orchestrator.mcp_server.server import BissetMCPServer
    tools = {t["name"] for t in BissetMCPServer()._build_tools()}
    assert {"step_set_feature", "step_get_feature", "step_validate_feature"} <= tools
```

(Class name `BissetMCPServer` verified at `server.py:37`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/mcp_server/tests/ -q`
Expected: 2 FAIL

- [ ] **Step 3: Implement**

In `client.py`, add to `_GET_TOOLS`:

```python
    "step_get_feature",
    "step_validate_feature",
```

In `server.py` `_build_tools`, insert after the `step_current` entry:

```python
            {"name": "step_set_feature",
             "description": "Submit Gherkin content for a step; Bisset validates, writes to the project features dir and registers content + hash",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "session_id": {"type": "string"},
                 "content": {"type": "string"}, "filename": {"type": "string"},
             }, "required": ["step_id", "session_id", "content"]}},
            {"name": "step_get_feature",
             "description": "Read the step's .feature from disk (truth); reports feature_drifted and file_missing",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "session_id": {"type": "string"},
             }, "required": ["step_id", "session_id"]}},
            {"name": "step_validate_feature",
             "description": "Dry-run validation of the step's feature: syntax_ok, steps_defined, undefined_steps",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "session_id": {"type": "string"},
             }, "required": ["step_id", "session_id"]}},
```

(Keep the existing schema style: every array/object property fully typed —
Copilot compatibility was the reason for past fixes here.)

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add orchestrator/mcp_server/server.py orchestrator/mcp_server/client.py orchestrator/mcp_server/tests/test_client_v2.py
git commit -m "feat(mcp): expose Gherkin tools over MCP"
```

---

### Task 9: behave robustness in demo + docs truthfulness

**Files:**
- Modify: `scripts/demo_bdd_gate.sh` (project_create call, phase 2/8)
- Modify: `docs/bdd-enforcement.md` (adapters table + new tools)
- Modify: `README.md` (tool count if mentioned)

- [ ] **Step 1: Add `--no-snippets` to the demo project**

In `scripts/demo_bdd_gate.sh`, change `\"test_args\":\"--format json\"` to
`\"test_args\":\"--format json --no-snippets\"` in the `project_create` call.
Rationale: with undefined steps, snippets corrupt behave's JSON output
(verified on behave 1.3.3) and the adapter would degrade to exit-code-only.

- [ ] **Step 2: Re-run the demo**

Run: `./scripts/demo_bdd_gate.sh`
Expected: `DEMO PASSED`, exit 0

- [ ] **Step 3: Update `docs/bdd-enforcement.md`**

In the adapters table change the behave invocation to
`behave --format json --no-snippets <feature>` and add below the table:

```markdown
Recommended `test_args` for behave projects: `--format json --no-snippets`.
With snippets enabled, behave corrupts its own JSON output when undefined
steps are present (verified on behave 1.3.3) and the adapter degrades to
exit-code-only parsing.

## Gherkin tools

| Tool | What it does |
|------|--------------|
| `step_set_feature` | Agent submits Gherkin; Bisset validates the structure, writes the file into `features_dir`, registers content + SHA-256 |
| `step_get_feature` | Reads the feature from disk (truth); reports `feature_drifted` / `file_missing` and realigns the registry |
| `step_validate_feature` | behave dry-run: `syntax_ok` and `steps_defined` as separate verdicts plus `undefined_steps[]` |

Drift policy: the human owns the spec. Manual edits never block execution;
they are detected (hash mismatch), reported in tool responses, logged as
`feature_drift` events, and the DB copy realigns to disk.
```

- [ ] **Step 4: Commit**

```bash
git add scripts/demo_bdd_gate.sh docs/bdd-enforcement.md README.md
git commit -m "docs+demo: --no-snippets for behave JSON, document Gherkin tools"
```

---

### Task 10: E2E extension

**Files:**
- Test: `orchestrator/tests/test_e2e.py`

- [ ] **Step 1: Write the e2e test (goes green immediately — integration check, not TDD)**

Append to `orchestrator/tests/test_e2e.py`:

```python
def test_gherkin_feature_lifecycle(client, tmp_path):
    """set -> get -> manual edit -> drift reported on read."""
    r = client.post("/project_create", json={
        "name": "gherkin-e2e", "path": str(tmp_path), "adapter": "behave",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={"project_id": pid, "workflow_type": "new_feature"})
    sid = _payload(r)["session_id"]
    r = client.post("/step_add", json={"session_id": sid, "title": "Calc feature", "order": 1})
    step_id = _payload(r)["step_id"]

    feature = "Feature: Calc\n  Scenario: Add\n    Given two numbers\n    When added\n    Then result\n"
    r = client.post("/step_set_feature", json={
        "step_id": step_id, "session_id": sid, "content": feature,
    })
    assert _payload(r)["written"] is True
    path = tmp_path / "features" / "calc-feature.feature"
    assert path.read_text() == feature

    # human edits the spec on disk
    path.write_text(feature + "    And audited\n")
    r = client.get(f"/step_get_feature?step_id={step_id}&session_id={sid}")
    body = _payload(r)
    assert body["feature_drifted"] is True

    # audit trail
    r = client.get(f"/event_log?session_id={sid}")
    types = {e["event_type"] for e in _payload(r)["events"]}
    assert {"feature_set", "feature_drift"} <= types
```

- [ ] **Step 2: Run the whole suite**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add orchestrator/tests/test_e2e.py
git commit -m "test(e2e): gherkin feature lifecycle — set, get, drift, audit trail"
```

---

### Task 11: Final verification + PR

- [ ] **Step 1: Full suite from a clean venv**

```bash
python3 -m venv /tmp/gherkin-verify-venv
/tmp/gherkin-verify-venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. /tmp/gherkin-verify-venv/bin/python3 -m pytest orchestrator/ -q
rm -rf /tmp/gherkin-verify-venv
```
Expected: all pass

- [ ] **Step 2: Demo still green**

Run: `./scripts/demo_bdd_gate.sh`
Expected: `DEMO PASSED`, exit 0

- [ ] **Step 3: Update design doc status**

In `docs/plans/2026-06-04-gherkin-tools-design.md` change `**Status:** Approved`
to `**Status:** Implemented`. Commit:

```bash
git add docs/plans/2026-06-04-gherkin-tools-design.md
git commit -m "docs: mark gherkin tools design as implemented"
```

- [ ] **Step 4: Push and open PR (GitHub is the CI reference)**

```bash
git push -u github dev/feature0010-gherkin-tools
gh pr create --repo damn-fine-pizza/bisset-mcp \
  --head dev/feature0010-gherkin-tools --base main \
  --title "feat: Gherkin tools — step_set_feature / step_get_feature / step_validate_feature" \
  --body "Implements the approved design (docs/plans/2026-06-04-gherkin-tools-design.md): disk = truth, DB = registry (SHA-256), drift detected and reported, behave dry-run validation with split syntax/steps verdicts. No Co-Authored-By trailers."
```

NOTE: never add Co-Authored-By or AI-attribution trailers to commits or PR bodies (user preference).

- [ ] **Step 5: Watch CI to green**

```bash
gh run list --repo damn-fine-pizza/bisset-mcp --branch dev/feature0010-gherkin-tools --limit 1
```
Expected: `completed success`
