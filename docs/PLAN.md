> **Historical design document.** This describes the v1 specification and does not match the current implementation. For current behavior see the README, `docs/bdd-enforcement.md`, and `docs/plans/2026-03-06-bisset-v2-design.md`.

# Claude MCP Server Specification Plan
## Analysis & Design Document for BDD-first Workflow Orchestration

**Project:** Bisset MCP → Claude MCP Adapter  
**Date:** 2026-03-06  
**Scope:** Analysis + Specifications for future implementation (no code yet)

---

## Executive Summary

Bisset MCP is a workflow orchestration server for BDD-first software development, currently designed for GitHub Copilot CLI. This plan documents a **comprehensive specification for adapting Bisset to Claude**, maintaining all core features while optimizing for Claude's capabilities and API patterns.

### Key Design Decision
- **Adaptation Level:** Adapted for Claude (not a 1:1 copy)
- **Architecture:** Same two-tier pattern (STDIO MCP proxy + FastAPI backend)
- **Features:** All (BDD workflow, sub-agents, autonomy, enforcement, architecture evaluation)
- **Target Models:** Haiku (fast), Sonnet (standard), Opus (high-reasoning)
- **Scope of Delivery:** API reference + architecture diagrams + implementation guide + code examples

---

## Part 1: Current State Analysis

### Bisset Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ GitHub Copilot CLI (via MCP client)                         │
└────────────────┬────────────────────────────────────────────┘
                 │ STDIO (MCP protocol)
                 ▼
┌──────────────────────────────────────┐
│ mcp_server (FastMCP)                 │
│ - STDIO ↔ HTTP bridge                │
│ - Tool registration                  │
│ - Prompt delivery                    │
└────────┬──────────────────────────────┘
         │ HTTP (POST /tools/*, POST /prompts/*)
         ▼
┌──────────────────────────────────────────────────────────────┐
│ workflow_server (FastAPI, :8765)                             │
│ - WorkflowEngine (business logic)                            │
│ - Storage (SQLite, WAL mode)                                 │
│ - Catalog (default questions/tasks)                          │
│ - Renderers (spec/ADR/feature file generation)              │
│ - BDD test runner integration                                │
└────────┬───────────────────────────────────────────────────┘
         │ SQLite
         ▼
    bisset-db/
    └── workflow.db (SCHEMA_VERSION=6)
```

### Core Components

#### 1. **mcp_server** (380 lines)
- **STDIO proxy** using FastMCP library
- **Tool registration:** ~20 tools exposed to client
- **Prompt registration:** System prompts for each workflow phase
- **HTTP client** to workflow_server
- **Session management:** Stateless per-request

#### 2. **workflow_server** (1889 lines total)
- **app.py (530 lines):** FastAPI HTTP endpoints
- **engine.py (805 lines):** Core workflow state machine & business logic
- **storage.py (363 lines):** SQLite DAL with WAL mode for concurrency
- **catalog.py (37 lines):** Default questions catalog
- **renderers.py (39 lines):** Markdown spec/ADR/feature file writers
- **models.py (26 lines):** Pydantic/dataclass models
- **security.py (81 lines):** Auth & request signing

#### 3. **Storage Layer** (SQLite, SCHEMA_VERSION=6)
Tables:
- `sessions` — project session metadata
- `questions` — interview Q&A per session
- `tasks` — work breakdown per session
- `task_test_runs` — BDD test results (passed, failed, coverage %)
- `meta` — session key-value store
- `artifacts` — file paths modified per task
- `proposals` — architecture proposals (OOP/Functional/Data-Oriented)

#### 4. **Workflow Phases** (6 phases + review)
1. **Phase 2:** Requirements interview (bisset-interview agent)
2. **Phase 2.5:** Requirements validation (bisset-requirements-validate)
3. **Phase 3:** Architecture evaluation (3 paradigm proposals)
4. **Phase 4:** Gherkin feature generation (bisset-test-gherkin)
5. **Phase 5:** Implementation (8 domain specialists + docs)
6. **Phase 6:** Coverage gate (80% BDD scenarios must pass)
+ **Review:** Conformance audit (any time, extracts requirements from code)

#### 5. **Exposed Tools** (~20)
- Session management: `new_session`, `switch_session`, `list_sessions`, `detect_session`
- Interview: `next_question`, `record_answer`
- Execution: `freeze_spec`, `next_task`, `add_task`, `accept_task_result`
- Testing: `run_tests`
- Introspection: `status`, `report`, `is_done`, `get_events`
- Architecture: `store_proposal`, `list_proposals`
- Autonomy: `run_until_blocked`
- Misc: `store_note`, `bootstrap_project`

---

## Part 2: Claude Integration Strategy

### Design Adaptation Points

#### 2.1 API Compatibility
**Current (Copilot CLI):**
- HTTP POST with JSON bodies
- Tool return type: `dict` (free-form)
- Prompts: Plain markdown strings

**Claude MCP Adaptation:**
- Keep HTTP POST pattern (backward-compatible with Bisset backend)
- Add explicit `TextContent` + `ToolResult` wrapper for Claude SDK
- Prompts: Structured prompt format (can use native Claude prompt caching for large specs)
- Error handling: Explicit `error` + `message` fields in all responses

#### 2.2 Model-Aware Routing
Add explicit model hints for routing sub-agents:

```json
{
  "phase": "phase_5_implement",
  "task_id": "auth-jwt",
  "recommended_model": {
    "default": "claude-3-sonnet",
    "for_refactoring": "claude-3-haiku",
    "for_architecture": "claude-3-opus"
  }
}
```

#### 2.3 Async Operation Hints
Bisset's `run_until_blocked` expects synchronous feedback loops. Claude SDK doesn't guarantee synchronous sub-calls. Adaptation:
- Add `async_mode` flag to `workflow_start()` — allows async sub-agent dispatch
- Return `pending` status when sub-agent is still running
- Provide polling endpoint: `GET /tools/workflow_status?session_id=X`

#### 2.4 Prompt Caching Strategy
Large specs generated in Phase 2 (frozen Q&A) can be cached:
- Auto-detect when spec exceeds 10K characters
- Add `cache_control` header to prompts
- Reduce token consumption for long-running sessions

---

## Part 3: Detailed Specifications

### 3.1 Storage Schema (SQLite, SCHEMA_VERSION=7 for Claude)

#### Table: `sessions`
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    name TEXT,
    created_at REAL,
    updated_at REAL,
    mcp_client TEXT,          -- NEW: 'copilot-cli' | 'claude-mcp' | 'generic'
    phase TEXT,               -- NEW: current workflow phase for replay
    sub_phase TEXT,           -- NEW: sub-phase state
    spec_frozen_at REAL       -- NEW: timestamp when spec frozen
);
```

#### Table: `questions`
```sql
CREATE TABLE questions (
    id TEXT,
    session_id TEXT,
    text TEXT,
    answer TEXT,
    answered_at REAL,
    order_index INTEGER,      -- NEW: for reproducible interview order
    PRIMARY KEY (id, session_id)
);
```

#### Table: `tasks`
```sql
CREATE TABLE tasks (
    id TEXT,
    session_id TEXT,
    title TEXT,
    description TEXT,
    acceptance_criteria TEXT,
    negative_acceptance_criteria TEXT,
    status TEXT,              -- 'pending' | 'in_progress' | 'done' | 'blocked'
    created_at REAL,
    done_at REAL,
    evidence TEXT,
    assigned_model TEXT,      -- NEW: 'haiku' | 'sonnet' | 'opus'
    PRIMARY KEY (id, session_id)
);
```

#### Table: `task_test_runs`
```sql
CREATE TABLE task_test_runs (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    session_id TEXT,
    run_at REAL,
    passed INTEGER,
    failed INTEGER,
    total INTEGER,
    coverage_pct REAL,
    ok INTEGER,               -- 1 if coverage_pct >= threshold
    runner_output TEXT,
    runner_type TEXT,         -- NEW: 'pytest' | 'behave' | 'cucumber' | etc
    line_coverage_pct REAL    -- NEW: line-by-line coverage metric
);
```

#### Table: `proposals` (NEW)
```sql
CREATE TABLE proposals (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    paradigm TEXT,            -- 'oop' | 'functional' | 'data-oriented'
    content TEXT,             -- Full markdown proposal
    score REAL,               -- 0-100: architecture fitness score
    created_at REAL
);
```

#### Table: `artifacts` (NEW)
```sql
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    session_id TEXT,
    file_path TEXT,
    change_type TEXT,         -- 'create' | 'modify' | 'delete'
    diff TEXT,                -- Unified diff (optional, for review)
    created_at REAL
);
```

---

### 3.2 HTTP API Reference

#### Base URL
```
http://localhost:8765
```

#### Authentication
- Optional: Bearer token in `Authorization: Bearer <token>` (for multi-user deployments)
- Default: unauthenticated (local development)

#### Error Response Format
```json
{
  "error": "error_code",
  "message": "Human-readable message",
  "details": {}
}
```

---

### 3.3 Tool Endpoints (Full Catalog)

#### Session Management

**POST /tools/workflow_new_session**
```
Request:
{
  "name": "MyProject"
}

Response:
{
  "session_id": "abc-123",
  "name": "MyProject",
  "created_at": 1234567890.5
}
```

**POST /tools/workflow_switch_session**
```
Request:
{
  "session_id": "abc-123"
}

Response:
{
  "session_id": "abc-123",
  "phase": "phase_2_interview",
  "active": true
}
```

**POST /tools/workflow_list_sessions**
```
Response:
{
  "sessions": [
    {
      "id": "abc-123",
      "name": "MyProject",
      "created_at": 1234567890.5,
      "updated_at": 1234567895.5,
      "phase": "phase_5_implement",
      "progress": {"tasks_done": 5, "tasks_total": 12}
    }
  ]
}
```

**POST /tools/workflow_detect_session**
```
Request:
{
  "cwd": "/path/to/project"
}

Response:
{
  "detected": true,
  "session_id": "abc-123",
  "name": "MyProject"
}
OR
{
  "detected": false,
  "available_sessions": [...]
}
```

#### Interview Phase

**POST /tools/workflow_start**
```
Request:
{
  "project_meta": {
    "name": "MyProject",
    "project_path": "/abs/path",
    "features_dir": "features",
    "test_runner": "pytest",
    "test_runner_args": ["--tb=short", "-q"],
    "bdd_coverage_threshold": 80,
    "use_line_coverage": true,
    "line_coverage_threshold": 80
  }
}

Response:
{
  "session_id": "abc-123",
  "phase": "phase_2_interview",
  "total_questions": 25,
  "first_question": {
    "id": "q1",
    "text": "What is the primary purpose of this project?",
    "category": "project-scope"
  }
}
```

**POST /tools/workflow_next_question**
```
Response:
{
  "done": false,
  "question": {
    "id": "q2",
    "text": "What are the key features to implement?",
    "category": "features",
    "answered": false
  }
}
OR
{
  "done": true,
  "message": "All questions answered. Call workflow_freeze_spec() to proceed."
}
```

**POST /tools/workflow_record_answer**
```
Request:
{
  "question_id": "q2",
  "answer_text": "User authentication, payment processing, reporting dashboard"
}

Response:
{
  "ok": true,
  "question_id": "q2",
  "recorded_at": 1234567890.5
}
```

**POST /tools/workflow_list_questions**
```
Request:
{
  "answered": null  -- null (all) | true (answered) | false (unanswered)
}

Response:
{
  "questions": [
    {
      "id": "q1",
      "text": "...",
      "answer": "...",
      "answered": true,
      "answered_at": 1234567890.5
    }
  ]
}
```

#### Spec Freeze & Architecture

**POST /tools/workflow_freeze_spec**
```
Response:
{
  "ok": true,
  "phase": "phase_2_5_requirements",
  "spec_path": "/path/to/spec.md",
  "adr_path": "/path/to/adr-0001.md",
  "workplan_path": "/path/to/workplan.md",
  "message": "Spec frozen. Call workflow_list_questions() to review Q&A, then architect to proceed."
}
```

**POST /tools/workflow_store_proposal**
```
Request:
{
  "paradigm": "oop",  -- | "functional" | "data-oriented"
  "content": "# OOP Architecture...\n\n## Self-Assessment: 92/100"
}

Response:
{
  "ok": true,
  "proposal_id": "prop-oop-1",
  "paradigm": "oop",
  "created_at": 1234567890.5
}
```

**POST /tools/workflow_list_proposals**
```
Response:
{
  "proposals": [
    {
      "id": "prop-oop-1",
      "paradigm": "oop",
      "score": 92.0,
      "created_at": 1234567890.5,
      "content_preview": "# OOP Architecture\n\n..."
    }
  ]
}
```

#### Execution Phase

**POST /tools/workflow_next_task**
```
Response:
{
  "done": false,
  "task": {
    "id": "auth-jwt",
    "title": "Implement JWT authentication",
    "description": "Add JWT-based auth to API endpoints",
    "acceptance_criteria": "Given a user\nWhen they login with credentials\nThen they receive a JWT token",
    "negative_acceptance_criteria": "Given invalid credentials\nWhen they attempt login\nThen an error is returned",
    "status": "pending",
    "recommended_model": "sonnet"
  }
}
OR
{
  "done": true,
  "message": "All tasks complete!"
}
```

**POST /tools/workflow_add_task**
```
Request:
{
  "task_id": "custom-task-1",
  "title": "Implement user preferences API",
  "description": "...",
  "acceptance_criteria": "Given a user...",
  "negative_acceptance_criteria": "..."
}

Response:
{
  "ok": true,
  "task_id": "custom-task-1",
  "feature_file_created": "/path/to/features/custom-task-1.feature"
}
```

**POST /tools/workflow_run_tests**
```
Request:
{
  "task_id": "auth-jwt"
}

Response:
{
  "ok": true,
  "task_id": "auth-jwt",
  "passed": 8,
  "failed": 0,
  "total": 8,
  "coverage_pct": 92.5,
  "coverage_meets_threshold": true,
  "duration_ms": 3240,
  "output_log_path": "/path/to/test-output.log"
}
```

**POST /tools/workflow_accept_task_result**
```
Request:
{
  "task_id": "auth-jwt",
  "summary": "Implemented JWT authentication with bearer token validation",
  "tests_run": [
    "test_user_login_success",
    "test_user_login_invalid_password"
  ],
  "test_results": {
    "passed": 8,
    "failed": 0
  },
  "artifacts_changed": [
    {"path": "src/auth.py", "change_type": "create"},
    {"path": "tests/test_auth.py", "change_type": "create"}
  ]
}

Response:
{
  "ok": true,
  "task_id": "auth-jwt",
  "status": "done",
  "accepted_at": 1234567890.5
}
```

#### Introspection & Status

**POST /tools/workflow_status**
```
Response:
{
  "session_id": "abc-123",
  "phase": "phase_5_implement",
  "sub_phase": "implementing",
  "tasks_total": 12,
  "tasks_done": 5,
  "tasks_pending": 7,
  "current_task": {
    "id": "auth-jwt",
    "title": "...",
    "status": "in_progress"
  },
  "last_test_run": {
    "task_id": "auth-jwt",
    "passed": 8,
    "failed": 0,
    "coverage_pct": 92.5
  },
  "last_error": null
}
```

**POST /tools/workflow_report**
```
Response:
{
  "phase": "phase_5_implement",
  "sub_phase": "implementing",
  "questions_answered": 25,
  "questions_total": 25,
  "tasks_done": 5,
  "tasks_total": 12,
  "spec_frozen": true,
  "spec_frozen_at": 1234567890.5,
  "estimated_coverage": 87.5,
  "message": "Implementation phase: 5/12 tasks complete, avg coverage 92%"
}
```

**POST /tools/workflow_is_done**
```
Response:
{
  "done": true,
  "message": "All tasks accepted and coverage gate passed (89.5% >= 80% threshold)"
}
```

**POST /tools/workflow_get_events**
```
Request:
{
  "limit": 50
}

Response:
{
  "events": [
    {
      "timestamp": 1234567890.5,
      "tool": "workflow_run_tests",
      "task_id": "auth-jwt",
      "args": {...},
      "result": {...},
      "success": true,
      "duration_ms": 3240
    }
  ],
  "total": 147,
  "returned": 50
}
```

#### Utility

**POST /tools/workflow_bootstrap_project**
```
Request:
{
  "cwd": "/path/to/project",
  "autodetect": true
}

Response:
{
  "ok": true,
  "project_type": "python",
  "project_path": "/path/to/project",
  "test_runner": "pytest",
  "test_runner_args": ["--tb=short", "-q"],
  "features_dir": "features"
}
```

**POST /tools/workflow_run_until_blocked**
```
Request:
{
  "max_iterations": 20,
  "max_minutes": 30
}

Response:
{
  "status": "blocked" | "done" | "timeout" | "iteration_limit",
  "iterations": 5,
  "tasks_accepted": 5,
  "reason": "Test failure in task 'payment-integration'",
  "blocked_task": {
    "id": "payment-integration",
    "status": "in_progress"
  },
  "test_result": {
    "passed": 3,
    "failed": 2,
    "coverage_pct": 65.5
  },
  "fix": "Test expects 'amount' field but implementation uses 'value'. Update test or code."
}
```

**POST /tools/workflow_store_note**
```
Request:
{
  "key": "architecture-decision-1",
  "content": "We chose async/await over callback-based concurrency because..."
}

Response:
{
  "ok": true,
  "key": "architecture-decision-1"
}
```

**POST /tools/workflow_advance_phase**
```
Request:
{
  "signal": "requirements_valid" | "requirements_incomplete" | "interview_updated" | "tasks_ready" | "features_written" | "implementation_complete" | "coverage_passed" | "coverage_failed"
}

Response:
{
  "ok": true,
  "previous_phase": "phase_2_5_requirements",
  "new_phase": "phase_3_architect",
  "message": "Advanced to phase_3_architect. Sub-agents ready for architecture evaluation."
}
```

---

### 3.4 MCP Protocol Integration

#### Tool Registration
```json
{
  "tools": [
    {
      "name": "workflow_new_session",
      "description": "Create a new workflow session for a project",
      "inputSchema": {
        "type": "object",
        "properties": {
          "name": {"type": "string", "description": "Project name"}
        }
      }
    },
    ... (20+ total tools)
  ]
}
```

#### Prompts (System-level)
Per-phase prompts:
- **Phase 2:** Interview guidelines (how to ask good questions, capture requirements)
- **Phase 2.5:** Validation checklist (completeness, consistency, testability)
- **Phase 3:** Architecture evaluation framework (paradigm scoring)
- **Phase 4:** Gherkin generation rules (BDD semantics, test coverage)
- **Phase 5:** Implementation domain routing (when to call which specialist)
- **Phase 6:** Coverage gate policy (when test coverage is "good enough")

---

## Part 4: Architecture Diagrams & Design Decisions

### 4.1 Phase State Machine

```
                   ┌─────────────────────┐
                   │  workflow_new_session  │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │  workflow_start     │
                   │  (project_meta)     │
                   └──────────┬──────────┘
                              │
                              ▼
          ┌───────────────────────────────────┐
          │ Phase 2: Interview               │
          │ bisset-interview reads Qs,       │
          │ records As                       │
          └─────────────┬─────────────────────┘
                        │ interview_complete
                        ▼
          ┌──────────────────────────────────┐
          │ Phase 2.5: Requirements          │
          │ bisset-requirements-validate     │
          │ checks: completeness,            │
          │ consistency, testability         │
          └──┬──────────────────────────┬────┘
             │                          │
        ✓ valid               ✗ incomplete
             │                          │
             │                          └──→ loop to Phase 2
             │
             ▼
    ┌──────────────────────────┐
    │ Phase 3: Architecture    │
    │ bisset-architect runs    │
    │ 3 paradigm specialists:  │
    │ - bisset-architect-oop   │
    │ - bisset-architect-fn    │
    │ - bisset-architect-dod   │
    └────────┬─────────────────┘
             │ tasks_ready
             ▼
   ┌──────────────────────────┐
   │ Phase 4: Gherkin         │
   │ bisset-test-gherkin      │
   │ generates .feature files │
   └────────┬─────────────────┘
            │ features_written
            ▼
   ┌──────────────────────────┐
   │ Phase 5: Implementation  │
   │ bisset-implement loops:  │
   │ for each task:           │
   │ - call domain specialist │
   │ - run_tests              │
   │ - accept_task_result     │
   └────────┬─────────────────┘
            │ implementation_complete
            ▼
   ┌──────────────────────────┐
   │ Phase 6: Coverage Gate   │
   │ bisset-test-gherkin      │
   │ runs full suite          │
   └──┬─────────────────┬─────┘
      │                 │
      ✓ ≥80%      ✗ <80%
      │                 │
      │                 └──→ loop to Phase 5
      │
      ▼
    DONE
```

### 4.2 Sub-Agent Routing (Phase 5)

```
bisset-implement (dispatcher)
    ├─→ task domain = "backend"
    │   └─→ bisset-backend (Python/Node/Go HTTP API logic)
    │
    ├─→ task domain = "frontend"
    │   └─→ bisset-frontend (React/Vue/Svelte components)
    │
    ├─→ task domain = "database"
    │   └─→ bisset-database (schema, migrations, queries)
    │
    ├─→ task domain = "cloud"
    │   └─→ bisset-cloud (AWS/GCP/Azure infrastructure)
    │
    ├─→ task domain = "devops"
    │   └─→ bisset-devops (CI/CD, Docker, Kubernetes)
    │
    ├─→ task domain = "embedded"
    │   └─→ bisset-embedded (firmware, MCU drivers)
    │
    ├─→ task domain = "ux"
    │   └─→ bisset-ux (design, interaction specs)
    │
    └─→ ALL TASKS DONE
        └─→ bisset-docs (README, API refs, guides)
            └─→ calls bisset-ux for user flow docs
```

### 4.3 Model Assignment Strategy (Claude-specific)

```
Task Complexity Analysis
    ├─→ Simple (CRUD, boilerplate)
    │   └─→ claude-3-haiku (fast, cost-effective)
    │
    ├─→ Medium (business logic, integration)
    │   └─→ claude-3-sonnet (balanced, default)
    │
    └─→ Complex (architecture, refactoring, debug)
        └─→ claude-3-opus (high-reasoning)
```

### 4.4 BDD Test Coverage Gate

```
Task Implementation
    │
    ├─→ workflow_run_tests(task_id)
    │   ├─→ Bisset executes test runner
    │   ├─→ Parses output (pytest, behave, cucumber)
    │   ├─→ Extracts: passed, failed, total, coverage%
    │   ├─→ Stores in task_test_runs table
    │   └─→ Returns: {ok, passed, failed, coverage_pct}
    │
    ├─→ Check: coverage_pct >= threshold (default 80%)?
    │   ├─→ YES: accept_task_result() allowed
    │   └─→ NO: block, request code changes
    │
    └─→ Task status: 'done'
```

---

## Part 5: Data Persistence & Replay

### 5.1 Session State Recovery
On crash/reconnection, Claude MCP can replay from checkpoint:

```python
# Pseudo-code
def recover_session(session_id):
    session = db.query('sessions', 'id = ?', [session_id])
    phase = session.phase
    sub_phase = session.sub_phase
    
    # Restore events log
    events = db.query('events', 'session_id = ? ORDER BY timestamp', [session_id])
    
    # Reconstruct state up to last good point
    for event in events:
        # Replay tool calls
        apply_event(event)
    
    return {
        'phase': phase,
        'sub_phase': sub_phase,
        'task_in_progress': get_current_task(session_id),
        'last_error': get_last_error(session_id)
    }
```

### 5.2 Audit Trail
Every tool invocation is logged:
```json
{
  "session_id": "abc-123",
  "timestamp": 1234567890.5,
  "tool": "workflow_run_tests",
  "arguments": {"task_id": "auth-jwt"},
  "result": {"ok": true, "passed": 8, "failed": 0},
  "duration_ms": 3240,
  "model": "claude-3-sonnet",
  "user_agent": "claude-mcp/1.0"
}
```

---

## Part 6: Implementation Roadmap (for future)

### Phase A: Foundation (MVP)
1. **Adapt storage schema** → Add `mcp_client`, `phase`, `sub_phase`, `spec_frozen_at` columns
2. **Port mcp_server** → Use official Claude Python SDK instead of FastMCP
3. **Add model-aware routing** → Recommended model hints in task objects
4. **Update API responses** → Wrap with Claude SDK `TextContent` + `ToolResult`

### Phase B: Claude Optimization
5. **Prompt caching** → Auto-detect large specs, add cache_control headers
6. **Async mode** → Handle sub-agent dispatch without blocking Claude
7. **Streaming support** → Long-running operations (run_until_blocked) stream progress

### Phase C: Sub-Agent System
8. **Port bisset-interview** → Interview phase logic
9. **Port bisset-requirements-validate** → Validation phase
10. **Port bisset-architect & paradigm specialists** → Architecture evaluation
11. **Port bisset-test-gherkin** → Feature generation & coverage gating
12. **Port bisset-implement & domain specialists** → Implementation dispatch

### Phase D: Testing & Hardening
13. **Integration tests** → MCP protocol compliance, Claude SDK contracts
14. **Load testing** → Concurrent sessions, stress-test storage
15. **Error handling** → Crash recovery, state repair, debugging tools

---

## Part 7: Deliverables Checklist

### Code (Phase A+)
- [ ] Adapted `mcp_server/__main__.py` (Claude SDK integration)
- [ ] Updated `workflow_server/storage.py` (schema v7)
- [ ] Updated `workflow_server/app.py` (Claude response wrappers)
- [ ] Updated `workflow_server/engine.py` (model-aware routing)
- [ ] New `workflow_server/claude_integration.py` (Prompt caching, model hints)

### Documentation
- [ ] **API Reference** (`docs/api-reference.md`)
  - All 20+ endpoints with request/response examples
  - Error codes and handling
  - Rate limiting (if applicable)
  
- [ ] **Architecture Diagrams** (`docs/architecture-claude.md`)
  - Phase state machine (Mermaid)
  - Sub-agent routing flowchart
  - Model assignment strategy
  - BDD coverage gate logic
  
- [ ] **Implementation Guide** (`docs/implementation-guide.md`)
  - Setup instructions (Claude SDK, environment)
  - Schema migration path (v6 → v7)
  - Testing strategy
  - Debugging & troubleshooting
  
- [ ] **Code Examples** (`docs/examples/`)
  - Starting a session (Python)
  - Recording interview answers (Python)
  - Freezing spec & running architecture phase (Python)
  - Implementing & testing a task (Python)
  - Autonomous loop usage (Python)

### Configuration
- [ ] `.env.example` additions (Claude API key, model defaults)
- [ ] `requirements.txt` updates (claude-sdk version)
- [ ] `docker-compose.yml` (if applicable)

---

## Part 8: Key Design Decisions (ADR-style)

### ADR-001: Keep Two-Tier Architecture
**Decision:** Maintain STDIO proxy + HTTP backend separation.  
**Rationale:**
- Allows reuse of existing workflow_server (battle-tested)
- Easier testing (decouple MCP protocol from business logic)
- Supports multi-user deployments (HTTP backend scales independently)
- Migration path: Can swap MCP proxy without touching backend

### ADR-002: Model-Aware Task Routing
**Decision:** Add `assigned_model` field to tasks; recommend models per task type.  
**Rationale:**
- Optimizes cost (Haiku for simple, Opus for complex)
- Respects Claude's strengths (Opus for reasoning, Sonnet for balanced)
- Allows users to override recommendations
- Future-proof: Easy to add new models

### ADR-003: Async Mode for Sub-Agents
**Decision:** Add `async_mode` flag; sub-agents can run independently.  
**Rationale:**
- Claude SDK doesn't guarantee synchronous nested calls
- Allows true parallelism (e.g., 3 paradigm specialists in Phase 3)
- Polling endpoint for status checks
- Better UX for long-running operations

### ADR-004: Prompt Caching Strategy
**Decision:** Auto-detect large specs (>10K chars), add cache_control headers.  
**Rationale:**
- Frozen specs can be very large (25K+ chars)
- Reduces token consumption for multi-turn sessions
- Claude API supports prompt caching (beta feature)
- Transparent to user (automatic)

---

## Part 9: Open Questions & Future Considerations

1. **Multi-turn conversation memory:** Should the MCP proxy maintain conversation history between sessions, or is session-based isolation sufficient?
2. **Tool result size limits:** Do response bodies have limits in Claude API? How to handle large specs/artifacts?
3. **Streaming support:** Should `run_until_blocked` stream progress, or wait for completion?
4. **Error recovery:** On mid-phase crash, auto-recover or require manual intervention?
5. **Cost tracking:** Should we log token usage per session/task for transparency?

---

## Conclusion

This specification provides a comprehensive blueprint for adapting Bisset MCP to Claude, maintaining all core BDD-first workflow features while optimizing for Claude's capabilities (model variety, prompt caching, async operations). The two-tier architecture ensures backward compatibility with the existing workflow_server, reducing implementation risk.

**Next step:** Implement Phase A (Foundation) using this specification as the contract between frontend (Claude MCP) and backend (workflow_server).

---

**Document Version:** 1.0  
**Status:** Ready for implementation planning  
**Reviewer Sign-off:** [Pending]
