# Gated artifact for non-behave projects — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `step_set_test_path`, a pointer-only tool that lets a step carry a non-Gherkin test artifact (e.g. a pytest module) so the test/gate loop engages for non-behave projects.

**Architecture:** A new engine method `set_test_path` validates a project-relative path (no traversal, must exist), writes only `feature_path`, and clears any stale Gherkin `feature_content`/`feature_hash` ("bare pointer"). It is exposed as an HTTP POST route and an MCP tool. No schema change — the existing `feature_path` column is reused. The end-to-end gate behaviour (red blocks, green advances) is proven against a real pytest subprocess.

**Tech Stack:** Python, FastAPI, SQLite, pytest. Test command: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`

**Baseline test count: 188.** Final expected: **204** (+16).

Reference design: `docs/plans/2026-06-10-gated-artifact-non-behave-design.md`.

---

## File structure

- `orchestrator/workflow_server/engine.py` — add module-level `safe_project_relative_path()` and `WorkflowEngine.set_test_path()`.
- `orchestrator/workflow_server/app.py` — add `@app.post("/step_set_test_path")`.
- `orchestrator/mcp_server/server.py` — add the `step_set_test_path` tool entry in `_build_tools()`.
- `orchestrator/mcp_server/client.py` — **no change** (generic `/{tool_name}` mapping; POST by default since not in `_GET_TOOLS`).
- Tests: `tests/test_engine_v2.py`, `tests/test_app_v2.py`, `mcp_server/tests/test_client_v2.py`.

---

## Task 1: Path-safety helper (`safe_project_relative_path`)

**Files:**
- Modify: `orchestrator/workflow_server/engine.py` (add module-level function near the other module helpers, after the imports / `DEFAULT_RULES` block, e.g. right before `class WorkflowEngine`)
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py`:

```python
from orchestrator.workflow_server.engine import safe_project_relative_path


def test_safe_project_relative_path_accepts_subdir():
    assert safe_project_relative_path("tests/test_foo.py") == "tests/test_foo.py"


def test_safe_project_relative_path_normalizes_inside():
    # a/../b stays inside the root -> normalized to b
    assert safe_project_relative_path("tests/../tests/test_foo.py") == "tests/test_foo.py"


def test_safe_project_relative_path_rejects_absolute():
    with pytest.raises(ValueError):
        safe_project_relative_path("/etc/passwd")


def test_safe_project_relative_path_rejects_traversal():
    with pytest.raises(ValueError):
        safe_project_relative_path("../evil.py")


def test_safe_project_relative_path_rejects_empty():
    with pytest.raises(ValueError):
        safe_project_relative_path("   ")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -k safe_project_relative_path -q`
Expected: FAIL with `ImportError: cannot import name 'safe_project_relative_path'`.

- [ ] **Step 3: Write minimal implementation**

In `orchestrator/workflow_server/engine.py`, add this module-level function (it only needs `os`, already imported), placed right before `class WorkflowEngine`:

```python
def safe_project_relative_path(path: str) -> str:
    """Normalize a project-relative artifact path.

    Rejects empty input, absolute paths, and any path that escapes the
    project root via traversal. Returns the normalized relative path.
    """
    raw = (path or "").strip()
    if not raw:
        raise ValueError("Empty test path")
    if os.path.isabs(raw):
        raise ValueError(f"Test path must be project-relative: {path!r}")
    norm = os.path.normpath(raw)
    if norm == ".." or norm.startswith(".." + os.sep) or os.path.isabs(norm):
        raise ValueError(f"Test path escapes project root: {path!r}")
    return norm
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -k safe_project_relative_path -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/engine.py orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "feat(engine): safe_project_relative_path helper for non-Gherkin test pointers"
```

---

## Task 2: Engine method `set_test_path`

**Files:**
- Modify: `orchestrator/workflow_server/engine.py` (add `set_test_path` method, e.g. right after `set_feature` / before `_detect_drift`)
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py`:

```python
def test_set_test_path_registers_pointer(engine, tmp_path):
    pid = engine.create_project("pyapp", str(tmp_path), test_runner="pytest", adapter="pytest")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Implement parser", "d", 1)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_parser.py").write_text("def test_x():\n    assert True\n")

    result = engine.set_test_path(step_id, sid, "tests/test_parser.py")
    assert result == {"feature_path": "tests/test_parser.py", "set": True}

    step = engine.db.get_step(step_id)
    assert step["feature_path"] == "tests/test_parser.py"
    assert step["feature_content"] is None
    assert step["feature_hash"] is None

    events = engine.db.list_events(sid)
    assert any(e["event_type"] == "test_path_set" for e in events)


def test_set_test_path_clears_stale_gherkin(engine, tmp_path):
    pid = engine.create_project("mix", str(tmp_path), test_runner="pytest", adapter="pytest")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "S", "d", 1)
    # first a Gherkin feature, then re-point at a pytest file
    engine.set_feature(step_id, sid, VALID_FEATURE)
    assert engine.db.get_step(step_id)["feature_content"] is not None
    (tmp_path / "test_s.py").write_text("def test_x():\n    assert True\n")

    engine.set_test_path(step_id, sid, "test_s.py")
    step = engine.db.get_step(step_id)
    assert step["feature_path"] == "test_s.py"
    assert step["feature_content"] is None
    assert step["feature_hash"] is None


def test_set_test_path_rejects_missing_file(engine, tmp_path):
    pid = engine.create_project("pyapp", str(tmp_path), adapter="pytest")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "S", "d", 1)
    with pytest.raises(ValueError, match="does not exist"):
        engine.set_test_path(step_id, sid, "tests/missing.py")


def test_set_test_path_rejects_traversal(engine, tmp_path):
    pid = engine.create_project("pyapp", str(tmp_path), adapter="pytest")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "S", "d", 1)
    with pytest.raises(ValueError):
        engine.set_test_path(step_id, sid, "../evil.py")


def test_set_test_path_unknown_session_raises(engine, tmp_path):
    pid = engine.create_project("pyapp", str(tmp_path), adapter="pytest")
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "S", "d", 1)
    with pytest.raises(ValueError, match="Session not found"):
        engine.set_test_path(step_id, "nonexistent", "test_s.py")


def test_set_test_path_unknown_step_raises(engine, tmp_path):
    pid = engine.create_project("pyapp", str(tmp_path), adapter="pytest")
    sid = engine.start_session(pid, "new_feature")
    with pytest.raises(ValueError, match="Step not found"):
        engine.set_test_path("nonexistent", sid, "test_s.py")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -k set_test_path -q`
Expected: FAIL with `AttributeError: 'WorkflowEngine' object has no attribute 'set_test_path'`.

- [ ] **Step 3: Write minimal implementation**

In `orchestrator/workflow_server/engine.py`, add this method to `WorkflowEngine` (right after `set_feature`):

```python
    def set_test_path(self, step_id: str, session_id: str, path: str) -> dict:
        """Point a step at an existing non-Gherkin test file (pointer-only).

        Stores only feature_path (project-relative, validated, must exist) and
        clears any stale Gherkin feature_content/feature_hash. Bisset stays
        agnostic about the file's content; run_tests reads disk at run time.
        """
        step = self.db.get_step(step_id)
        if not step:
            raise ValueError(f"Step not found: {step_id}")
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        project = self.db.get_project(session["project_id"])
        if not project:
            raise ValueError(f"Project not found: {session['project_id']}")

        rel_path = safe_project_relative_path(path)
        abs_path = os.path.join(project["path"], rel_path)
        if not os.path.isfile(abs_path):
            raise ValueError(f"Test file does not exist: {rel_path}")

        self.db.update_step(step_id, feature_path=rel_path,
                            feature_content=None, feature_hash=None)
        self.db.add_event(session_id, "test_path_set", step_id=step_id,
                          data={"feature_path": rel_path})
        return {"feature_path": rel_path, "set": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -k set_test_path -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/engine.py orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "feat(engine): set_test_path registers a bare non-Gherkin test pointer"
```

---

## Task 3: HTTP route `/step_set_test_path`

**Files:**
- Modify: `orchestrator/workflow_server/app.py` (add route right after the `step_set_feature` route, before `step_get_feature`)
- Test: `orchestrator/workflow_server/tests/test_app_v2.py`

- [ ] **Step 1: Write the failing tests**

Add the new-route happy-path test to `orchestrator/workflow_server/tests/test_app_v2.py` (place it near the other `step_set_*` endpoint tests; `_payload` and `client` are existing helpers/fixtures):

```python
def test_step_set_test_path_endpoint(client, tmp_path):
    r = client.post("/project_create", json={
        "name": "py-app", "path": str(tmp_path),
        "test_runner": "pytest", "adapter": "pytest",
    })
    pid = _payload(r)["project_id"]
    r = client.post("/session_start", json={"project_id": pid, "workflow_type": "new_feature"})
    sid = _payload(r)["session_id"]
    r = client.post("/step_add", json={"session_id": sid, "title": "Parse", "order": 1})
    step_id = _payload(r)["step_id"]

    (tmp_path / "test_parse.py").write_text("def test_x():\n    assert True\n")
    r = client.post("/step_set_test_path", json={
        "step_id": step_id, "session_id": sid, "path": "test_parse.py",
    })
    assert r.status_code == 200
    body = _payload(r)
    assert body["set"] is True
    assert body["feature_path"] == "test_parse.py"
```

Also add `step_set_test_path` to the 400-guard parametrize list. Find the `@pytest.mark.parametrize` list feeding `test_missing_required_field_returns_400` and add this tuple next to the `("/step_set_feature", "STEP_SET_FEATURE_ERROR"),` entry:

```python
    ("/step_set_test_path", "STEP_SET_TEST_PATH_ERROR"),
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_app_v2.py -k "step_set_test_path or missing_required_field" -q`
Expected: FAIL — the happy-path test gets a 404/500 (no route) and the parametrized `/step_set_test_path` case fails (route missing → not the 400 contract).

- [ ] **Step 3: Write minimal implementation**

In `orchestrator/workflow_server/app.py`, add this route immediately after the `step_set_feature` route (after its closing `return ResponseWrapper.error(...)` line, before `@app.get("/step_get_feature")`):

```python
@app.post("/step_set_test_path")
async def step_set_test_path(request: Request) -> Dict[str, Any]:
    """Point a step at an existing non-Gherkin test file (pointer-only)."""
    start = time.time()
    try:
        body = await request.json()
        try:
            step_id = body["step_id"]
            session_id = body["session_id"]
            path = body["path"]
        except KeyError as e:
            return ResponseWrapper.error(f"Missing required field: {e}", "STEP_SET_TEST_PATH_ERROR", 400)
        result = request.app.state.engine.set_test_path(step_id, session_id, path)
        duration = (time.time() - start) * 1000
        return ResponseWrapper.success(result, duration)
    except Exception as e:
        return ResponseWrapper.error(str(e), "STEP_SET_TEST_PATH_ERROR", 500)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_app_v2.py -k "step_set_test_path or missing_required_field" -q`
Expected: PASS (happy-path test + all parametrized 400 cases, now including `/step_set_test_path`).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/app.py orchestrator/workflow_server/tests/test_app_v2.py
git commit -m "feat(app): POST /step_set_test_path route with 400 guard"
```

---

## Task 4: MCP tool exposure

**Files:**
- Modify: `orchestrator/mcp_server/server.py` (add tool entry in `_build_tools()` next to `step_set_feature`)
- Test: `orchestrator/mcp_server/tests/test_client_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `orchestrator/mcp_server/tests/test_client_v2.py`:

```python
def test_set_test_path_tool_exposed():
    from orchestrator.mcp_server.server import BissetMCPServer
    tools = {t["name"] for t in BissetMCPServer()._build_tools()}
    assert "step_set_test_path" in tools


def test_set_test_path_routing():
    from orchestrator.mcp_server.client import _GET_TOOLS
    # it is a write: must go through POST, never GET
    assert "step_set_test_path" not in _GET_TOOLS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/mcp_server/tests/test_client_v2.py -k set_test_path -q`
Expected: FAIL — `test_set_test_path_tool_exposed` fails (tool not in set). (`test_set_test_path_routing` passes trivially since the name is absent from `_GET_TOOLS` — that is the intended invariant.)

- [ ] **Step 3: Write minimal implementation**

In `orchestrator/mcp_server/server.py`, inside `_build_tools()`, add this entry immediately after the `step_set_feature` dict (before `step_get_feature`):

```python
            {"name": "step_set_test_path",
             "description": "Point a step at an existing non-Gherkin test file (e.g. a pytest module) so the test/gate loop engages; registers the project-relative path, no Gherkin validation",
             "inputSchema": {"type": "object", "properties": {
                 "step_id": {"type": "string"}, "session_id": {"type": "string"},
                 "path": {"type": "string"},
             }, "required": ["step_id", "session_id", "path"]}},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/mcp_server/tests/test_client_v2.py -k set_test_path -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/mcp_server/server.py orchestrator/mcp_server/tests/test_client_v2.py
git commit -m "feat(mcp): expose step_set_test_path tool"
```

---

## Task 5: End-to-end gate proof (pytest step, red blocks / green advances)

This is the success criterion: prove the gate actually closes for the exact case
the feature exists for, against a **real pytest subprocess** — not just unit tests.

**Files:**
- Test: `orchestrator/workflow_server/tests/test_engine_v2.py`

- [ ] **Step 1: Write the failing test**

Append to `orchestrator/workflow_server/tests/test_engine_v2.py` (uses `sys` for a portable pytest invocation; add `import sys` at the top of the file if not already present):

```python
def test_pytest_step_gate_red_blocks_green_advances(engine, tmp_path):
    # A non-behave project: real pytest subprocess, default gate (tests_only).
    pid = engine.create_project(
        "pyproj", str(tmp_path),
        test_runner=sys.executable,
        test_args="-m pytest -q -p no:cacheprovider",
        adapter="pytest",
    )
    sid = engine.start_session(pid, "new_feature")
    step_id = engine.add_step(sid, "Add feature", "d", 1)

    target = tmp_path / "test_target.py"
    # RED: failing test
    target.write_text("def test_it():\n    assert False\n")
    engine.set_test_path(step_id, sid, "test_target.py")

    engine.run_tests(step_id, sid)
    action_red = engine.complete_step(step_id, sid)
    assert action_red == "retry"  # gate blocks: red never advances

    # GREEN: same target now passes
    target.write_text("def test_it():\n    assert True\n")
    engine.run_tests(step_id, sid)
    action_green = engine.complete_step(step_id, sid)
    assert action_green == "advance"  # gate opens only on green
```

- [ ] **Step 2: Run test to verify it fails (or errors) before the feature is wired**

> If Tasks 1–2 are already merged, this test should PASS directly — it depends only on `set_test_path`. Run it to confirm the end-to-end behaviour holds. If it is being written before Task 2, it fails with `AttributeError: set_test_path`.

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -k pytest_step_gate -q`
Expected (pre-Task 2): FAIL with `AttributeError`. Expected (post-Task 2): PASS.

- [ ] **Step 3: No new implementation needed**

The behaviour is delivered by `set_test_path` (Task 2) plus the existing
`run_tests` / `complete_step` / default rules. This task adds the proving test
only. If the test fails for a reason other than a missing `set_test_path`,
debug with superpowers:systematic-debugging before proceeding.

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/workflow_server/tests/test_engine_v2.py -k pytest_step_gate -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/workflow_server/tests/test_engine_v2.py
git commit -m "test(engine): prove pytest step gate engages (red blocks, green advances)"
```

---

## Task 6: Documentation + full-suite verification

**Files:**
- Modify: `docs/bdd-enforcement.md` (Gherkin/pipeline tools section)
- Modify: `docs/ROADMAP.md` (move the backlog item to Delivered)

- [ ] **Step 1: Update `docs/bdd-enforcement.md`**

In the "Gherkin tools" table (or right after it), add a row/note documenting the
new tool. Insert after the `step_validate_feature` row:

```markdown
| `step_set_test_path` | Points a step at an existing non-Gherkin test file (e.g. a pytest module) so the test/gate loop engages; registers the project-relative path (must exist, no traversal), clears any Gherkin content/hash. Pointer-only: Bisset never writes or parses the file |
```

Also update the "Limitations" bullet about `feature_path`:

Find:
```markdown
- A step without `feature_path` produces `no_tests` → `ask_user` under the
  default rules (graceful degradation, never silent acceptance).
```
Replace with:
```markdown
- A step without `feature_path` produces `no_tests` → `ask_user` under the
  default rules (graceful degradation, never silent acceptance). Behave steps
  get `feature_path` from `step_set_feature`; non-behave steps (pytest/generic)
  get it from `step_set_test_path`, which points at the test file directly.
```

- [ ] **Step 2: Update `docs/ROADMAP.md`**

Remove the "gated artifact is behave-shaped" bullet from the "Next → Hardening
backlog" list and add a line under "Delivered":

```markdown
- **Non-behave gated artifact** — `step_set_test_path`: a pointer-only tool that
  registers an existing test file (e.g. a pytest module) as a step's run target,
  so non-behave projects engage the test/gate loop without Gherkin. Gate proven
  end-to-end (red blocks, green advances) against a real pytest subprocess
```

- [ ] **Step 3: Run the full suite from the venv**

Run: `PYTHONPATH=. .venv/bin/python3 -m pytest orchestrator/ -q`
Expected: **204 passed** (188 baseline + 16 new: 5 helper + 6 engine + 2 app + 2 mcp + 1 end-to-end).

- [ ] **Step 4: Run the BDD gate demo (regression guard)**

Run: `./scripts/demo_bdd_gate.sh`
Expected: the demo still passes (behave gate unaffected).

- [ ] **Step 5: Commit**

```bash
git add docs/bdd-enforcement.md docs/ROADMAP.md
git commit -m "docs: document step_set_test_path; mark non-behave gated artifact delivered"
```

---

## Self-review notes

- **Spec coverage:** pointer-only role → Task 2 (`feature_content`/`feature_hash`
  cleared). Bare pointer → Task 2 (only `feature_path` set). Execute-loop scope →
  no analysis changes anywhere. Mandatory existence check → Task 2
  (`rejects_missing_file`). Path safety → Task 1. New tool vs `step_edit` (audit
  event) → Task 2 (`test_path_set` event asserted). No schema change → confirmed
  (reuses `feature_path`; `SCHEMA_VERSION` untouched). End-to-end success
  criterion → Task 5.
- **Type consistency:** method `set_test_path(step_id, session_id, path)` and
  return `{"feature_path", "set"}` used identically in engine, app route, and
  tests. Event name `test_path_set` consistent across design + plan. Error code
  `STEP_SET_TEST_PATH_ERROR` consistent between route and parametrize entry.
- **Count:** 188 → 204 (+16).
