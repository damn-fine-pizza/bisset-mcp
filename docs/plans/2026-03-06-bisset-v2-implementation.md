# Bisset v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite Bisset MCP as a workflow orchestrator with user-defined pipelines, Gherkin-gated steps, and a declarative rule engine.

**Architecture:** Refactor evolutionary — keep FastAPI + SQLite + client.py + server.sh. Rewrite storage schema, engine, endpoints, MCP server. Add rule engine DSL and test runner adapters.

**Tech Stack:** Python 3.14, FastAPI, SQLite, httpx, fastmcp (or mcp SDK)

**Design doc:** `docs/plans/2026-03-06-bisset-v2-design.md`

---

### Task 1: New Storage Schema

**Files:**
- Rewrite: `claude/orchestrator/workflow_server/storage.py`
- Create: `claude/orchestrator/workflow_server/tests/test_storage_v2.py`

**Step 1: Write failing tests for new schema**

Tests cover: create_project, create_session, write_isolation (locked project only),
read_cross_project, add_step, add_test_run, add_event.

See test file for full test code. 7 tests total.

**Step 2: Run tests to verify they fail**

Run: `cd claude && python -m pytest orchestrator/workflow_server/tests/test_storage_v2.py -v`
Expected: FAIL — old Storage class doesn't have new methods

**Step 3: Rewrite storage.py with new schema**

New schema (replaces everything):
- Tables: `projects`, `sessions`, `steps`, `test_runs`, `events`
- `lock_project(id)` sets `_locked_project_id`
- All write methods use `_locked_project_id`
- Read methods accept optional `project_id` parameter
- Fresh migration (v1 only — old data not preserved)
- DB path defaults to `~/.bisset/bisset.db`

Key method signatures:

```
# Project
create_project(name, path, test_runner, test_args, adapter, features_dir) -> str
get_project(project_id) -> dict | None
get_project_by_path(path) -> dict | None
list_projects() -> list[dict]
lock_project(project_id) -> bool
update_project(project_id, **kwargs) -> None

# Session
create_session(workflow_type, default_rules=None) -> str
get_session(session_id) -> dict | None
list_sessions(project_id=None) -> list[dict]
update_session_status(session_id, status) -> None

# Step
add_step(session_id, title, description, order, ...) -> str
get_step(step_id) -> dict | None
list_steps(session_id) -> list[dict]
update_step(step_id, **kwargs) -> None
remove_step(step_id) -> bool
get_current_step(session_id) -> dict | None
reorder_steps(session_id, step_ids) -> None

# Test Run
add_test_run(step_id, session_id, passed, failed, coverage, runner_output) -> str
get_test_run(run_id) -> dict | None
get_latest_test_run(step_id) -> dict | None

# Event
add_event(session_id, event_type, step_id=None, data=None) -> str
list_events(session_id, limit=100) -> list[dict]
```

**Step 4: Run tests to verify they pass**

Expected: PASS all 7 tests

**Step 5: Commit**

`feat(storage): rewrite schema for Bisset v2`

---

### Task 2: Rule Engine

**Files:**
- Create: `claude/orchestrator/workflow_server/rules.py`
- Create: `claude/orchestrator/workflow_server/tests/test_rules.py`

**Step 1: Write failing tests for rule engine**

Tests cover: advance_on_passing_tests, retry_on_failing, ask_user_after_max_retries,
ask_user_on_human_approval_gate, ask_user_when_no_tests, abort_fallback,
step_override_rules, invalid_when_raises. 8 tests total.

**Step 2: Run tests to verify they fail**

Expected: FAIL — module not found

**Step 3: Implement rule engine**

```python
class Action(str, Enum):
    ADVANCE = "advance"
    RETRY = "retry"
    ASK_USER = "ask_user"
    ABORT = "abort"
    SKIP = "skip"

ALLOWED_VARS = {
    "tests_pass", "tests_fail", "coverage", "retries",
    "gate", "no_tests", "step.order", "always",
}

class RuleEngine:
    def __init__(self, rules: list[dict]):
        self.rules = rules

    def evaluate(self, **context) -> Action:
        context["always"] = True
        for rule in self.rules:
            if self._eval_when(rule["when"], context):
                return Action(rule["then"])
        return Action.ABORT

    def _eval_when(self, expr: str, context: dict) -> bool:
        # Safe expression parser — NO eval() or exec().
        # Hand-written tokenizer + recursive descent evaluator.
        # Supports: AND, OR, NOT, ==, !=, >=, <=, >, <
        # All identifiers validated against ALLOWED_VARS.
        # Unknown variables raise ValueError.
        ...
```

**Step 4: Run tests to verify they pass**

Expected: PASS all 8 tests

**Step 5: Commit**

`feat(rules): declarative DSL rule engine with when/then evaluation`

---

### Task 3: Test Runner Adapters

**Files:**
- Create: `claude/orchestrator/workflow_server/adapters.py`
- Create: `claude/orchestrator/workflow_server/tests/test_adapters.py`

**Step 1: Write failing tests**

Tests cover: AdapterResult properties (total, all_passed),
GenericAdapter pass/fail, PytestAdapter parse, get_adapter factory. 5 tests total.

**Step 2: Run tests to verify they fail**

**Step 3: Implement adapters**

```python
@dataclass
class AdapterResult:
    passed: int = 0
    failed: int = 0
    coverage: float = 0.0
    errors: list[str] = field(default_factory=list)
    raw_output: str = ""

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.passed >= 0

class GenericAdapter:
    # exit_code 0 = pass, else fail, no coverage
    ...

class PytestAdapter:
    # parse "X passed, Y failed" from stdout
    ...

class BehaveAdapter:
    # parse behave --format json output
    ...

def get_adapter(name: str):
    adapters = {"pytest": PytestAdapter, "behave": BehaveAdapter, "generic": GenericAdapter}
    return adapters.get(name, GenericAdapter)()
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

`feat(adapters): test runner adapters — generic, pytest, behave`

---

### Task 4: Workflow Engine

**Files:**
- Rewrite: `claude/orchestrator/workflow_server/engine.py`
- Create: `claude/orchestrator/workflow_server/tests/test_engine_v2.py`

**Step 1: Write failing tests**

Tests cover: create_project_and_session, add_steps_and_get_current,
step_complete_advance, step_complete_retry, step_complete_ask_user_after_retries,
session_resume, project_lock_isolation. 7 tests total.

**Step 2: Run tests to verify they fail**

**Step 3: Implement engine**

```python
class WorkflowEngine:
    def __init__(self, db: Storage):
        self.db = db

    def create_project(self, name, path, **config) -> str
    def detect_project(self, cwd) -> dict | None
    def start_session(self, project_id, workflow_type, default_rules=None) -> str
    def resume_session(self, project_id) -> str
    def session_status(self, session_id) -> dict
    def add_step(self, session_id, title, description, order, **kwargs) -> str
    def current_step(self, session_id) -> dict | None
    def record_test_run(self, step_id, session_id, passed, failed, coverage, runner_output="") -> str
    def complete_step(self, step_id, session_id) -> str  # returns Action string
    def skip_step(self, step_id, session_id, reason) -> None
    def run_tests(self, step_id, session_id) -> AdapterResult  # subprocess
```

`complete_step` is the core:
1. Get latest test_run for step
2. Build context (tests_pass, coverage, retries, gate, etc.)
3. Get rules (step override or session default)
4. Evaluate with RuleEngine
5. Apply action (update step status, increment retries, etc.)
6. Log event
7. Return action string

**Step 4: Run tests, verify pass**

**Step 5: Commit**

`feat(engine): workflow engine with rule evaluation, gate logic, session resume`

---

### Task 5: FastAPI Endpoints

**Files:**
- Rewrite: `claude/orchestrator/workflow_server/app.py`
- Create: `claude/orchestrator/workflow_server/tests/test_app_v2.py`

**Step 1: Write failing tests**

Tests cover: health, project_create, session_start, pipeline_view.

**Step 2: Run tests to verify they fail**

**Step 3: Rewrite app.py**

Replace all endpoints. Keep FastAPI + ResponseWrapper + lifespan pattern.
New endpoints — one per tool from design doc. Zero logic in endpoints,
all forwarded to engine.

Storage init uses `~/.bisset/bisset.db`.

**Step 4: Run tests, verify pass**

**Step 5: Commit**

`feat(api): rewrite FastAPI endpoints for Bisset v2 tool set`

---

### Task 6: MCP Server Rewrite

**Files:**
- Rewrite: `claude/orchestrator/mcp_server/server.py`
- Rewrite: `claude/orchestrator/mcp_server/client.py`
- Create: `claude/orchestrator/mcp_server/tests/test_server_v2.py`

**Step 1: Write failing tests for client.py URL mapping**

**Step 2: Run tests, verify fail**

**Step 3: Rewrite client.py**

Update tool-to-endpoint mapping and GET/POST classification.

**Step 4: Rewrite server.py**

Replace hand-rolled JSON-RPC with `fastmcp` or `mcp` SDK. Expose:
- All tools from design doc
- Resources: `project://current`, `session://current`, `pipeline://current`, `history://sessions`
- Prompts: `bisset/interviewer`, `bisset/architect`, `bisset/analyzer`, `bisset/implementer`, `bisset/test-writer`

Resources read from DB via HTTP calls to workflow_server.
Prompts are templates composed with DB data + Claude context.

**Step 5: Run tests, verify pass**

**Step 6: Commit**

`feat(mcp): rewrite MCP server with SDK, new tool set, resources, prompts`

---

### Task 7: Prompt Template System

**Files:**
- Rewrite: `claude/orchestrator/mcp_server/prompts.py`
- Create: `claude/orchestrator/mcp_server/tests/test_prompts_v2.py`

**Step 1: Write failing tests**

Tests cover: template_render with DB and context vars,
missing_context_var replacement, registry_get_prompt.

**Step 2: Run tests, verify fail**

**Step 3: Implement prompt template system**

```python
class PromptTemplate:
    def __init__(self, name: str, template: str):
        self.name = name
        self.template = template

    def render(self, db_vars: dict, context_vars: dict) -> str:
        # Merge vars, replace {{key}} with values
        # Missing vars replaced with "[not provided: key]"
        ...

class PromptRegistry:
    # 5 templates: bisset/interviewer, architect, analyzer,
    # implementer, test-writer
    # Each uses {{project.*}}, {{step.*}}, {{session.*}}, {{context.*}}
    ...
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

`feat(prompts): template system with DB + context variable composition`

---

### Task 8: Cleanup Dead Code

**Step 1: Run full test suite to confirm new tests pass**

Run: `cd claude && python -m pytest orchestrator/ -v`

**Step 2: Remove old test files**

Delete: test_engine.py, test_storage_v7.py, test_app.py,
test_server.py, test_prompts.py (all v1 versions)

**Step 3: Run full test suite again**

Expected: All new tests pass, no old tests remain

**Step 4: Commit**

`chore: remove v1 dead code, old tests, unused modules`

---

### Task 9: End-to-End Integration Test

**Files:**
- Create: `claude/orchestrator/tests/test_e2e.py`

**Step 1: Write e2e test**

Full lifecycle: create project, start session, add steps,
record test runs, complete steps, verify session completed.
Uses FastAPI TestClient, no external server needed.

**Step 2: Run e2e test**

Expected: PASS

**Step 3: Commit**

`test: end-to-end integration test for full pipeline lifecycle`

---

## Task Dependency Graph

```
  1 (Storage)  ─────┐
  2 (Rules)    ─────┤──► 4 (Engine) ──► 5 (API) ──► 6 (MCP)
  3 (Adapters) ─────┘                      │            │
  7 (Prompts)  ────────────────────────────┘            │
                                                        v
                                         8 (Cleanup) ◄──┘
                                         9 (E2E) ◄── 5
```

Tasks 1, 2, 3, 7 are independent and can be parallelized.
Task 4 depends on 1+2+3. Task 5 depends on 4. Task 6 depends on 5.
