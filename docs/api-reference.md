> **Historical design document.** This describes the v1 specification and does not match the current implementation. For current behavior see the README, `docs/bdd-enforcement.md`, and `docs/plans/2026-03-06-bisset-v2-design.md`.

# BissetMCP API Reference

The workflow server exposes an HTTP API consumed by the STDIO MCP proxy. Every response is wrapped in the **Claude SDK TextContent** format for compatibility with Claude's tool-result schema.

## Base URL

```
http://localhost:8765
```

## Authentication

No authentication is required by default. When deploying in a multi-user environment, place the server behind a reverse proxy that enforces access controls.

## Response Format

All endpoints (except `/health` and `/info`) return the same envelope:

```json
{
  "content": [
    { "type": "text", "text": "<JSON-encoded payload>" }
  ],
  "is_error": false,
  "metadata": {
    "success": true,
    "duration_ms": 45.2
  }
}
```

### Error Response

```json
{
  "content": [
    { "type": "text", "text": "{\"error\": \"Session not found\", \"code\": \"NOT_FOUND\"}" }
  ],
  "is_error": true,
  "metadata": {
    "success": false,
    "error_code": "NOT_FOUND",
    "status": 404
  }
}
```

---

## Endpoints

### GET /health

Health check. Returns plain JSON (not wrapped).

**Response**

```json
{ "status": "healthy", "version": "1.0.0", "service": "claude-bisset-workflow" }
```

**cURL**

```bash
curl http://localhost:8765/health
```

---

### GET /info

Server capabilities. Returns plain JSON.

**Response**

```json
{
  "name": "Claude Bisset Workflow Server",
  "version": "1.0.0",
  "mcp_protocol": "stdio",
  "features": [
    "workflow_sessions", "interview_questions", "spec_management",
    "task_routing", "model_aware_assignment", "background_jobs",
    "prompt_caching", "async_mode"
  ]
}
```

**cURL**

```bash
curl http://localhost:8765/info
```

---

### POST /workflow_new_session

Create a new workflow session.

**Query Parameters**

| Name           | Type    | Default      | Description                          |
|----------------|---------|--------------|--------------------------------------|
| `project_name` | string  | `""`         | Human-readable project name          |
| `mcp_client`   | string  | `"claude-mcp"` | MCP client identifier              |
| `async_mode`   | boolean | `false`      | Enable async sub-agent execution     |

**Response payload** (inside `content[0].text`):

```json
{
  "id": "a1b2c3d4",
  "name": "my-app",
  "created_at": 1712345678.9,
  "updated_at": 1712345678.9,
  "mcp_client": "claude-mcp",
  "phase": "interview",
  "sub_phase": null,
  "spec_frozen_at": null
}
```

**Error codes**: `SESSION_CREATE_ERROR` (500)

**cURL**

```bash
curl -X POST "http://localhost:8765/workflow_new_session?project_name=my-app&mcp_client=claude-mcp"
```

---

### GET /workflow_detect_session

Detect (or auto-create) the current session. Returns the most-recently created session, or creates a new one if none exists.

**Response payload**: same shape as `workflow_new_session`.

**Error codes**: `SESSION_DETECT_ERROR` (500)

**cURL**

```bash
curl http://localhost:8765/workflow_detect_session
```

---

### GET /workflow_get_session/{session_id}

Get full details for a session.

**Path Parameters**

| Name         | Type   | Description |
|--------------|--------|-------------|
| `session_id` | string | Session ID  |

**Response payload**: session dict (same as `workflow_new_session`).

**Error codes**: `NOT_FOUND` (404), `SESSION_GET_ERROR` (500)

**cURL**

```bash
curl http://localhost:8765/workflow_get_session/a1b2c3d4
```

---

### POST /workflow_switch_session

Switch the active session context.

**Query Parameters**

| Name         | Type   | Description              |
|--------------|--------|--------------------------|
| `session_id` | string | Session to activate      |

**Response payload**: session dict.

**Error codes**: `NOT_FOUND` (404), `SESSION_SWITCH_ERROR` (500)

**cURL**

```bash
curl -X POST "http://localhost:8765/workflow_switch_session?session_id=a1b2c3d4"
```

---

### GET /workflow_list_sessions

List all sessions ordered by creation time.

**Response payload**

```json
{
  "sessions": [
    {
      "id": "a1b2c3d4",
      "name": "my-app",
      "phase": "interview",
      ...
    }
  ]
}
```

**Error codes**: `SESSION_LIST_ERROR` (500)

**cURL**

```bash
curl http://localhost:8765/workflow_list_sessions
```

---

### POST /workflow_start_interview/{session_id}

Initialize the interview phase and return the first unanswered question.

**Path Parameters**: `session_id`

**Response payload** (question available):

```json
{
  "id": "q-001",
  "text": "What is the primary purpose of this system?",
  "session_id": "a1b2c3d4"
}
```

**Response payload** (all answered):

```json
{ "signal": "interview_complete", "message": "No questions available" }
```

**Error codes**: `INTERVIEW_START_ERROR` (500)

**cURL**

```bash
curl -X POST http://localhost:8765/workflow_start_interview/a1b2c3d4
```

---

### GET /workflow_next_question/{session_id}

Get the next unanswered question.

**Path Parameters**: `session_id`

**Response payload**: same as `workflow_start_interview`, or `{"signal": "interview_complete"}`.

**cURL**

```bash
curl http://localhost:8765/workflow_next_question/a1b2c3d4
```

---

### POST /workflow_record_answer/{session_id}/{question_id}

Record an answer to a question.

**Path Parameters**: `session_id`, `question_id`

**Query Parameters**

| Name     | Type   | Description       |
|----------|--------|-------------------|
| `answer` | string | Answer text       |

**Response payload**

```json
{ "question_id": "q-001", "status": "recorded" }
```

**Error codes**: `ANSWER_RECORD_ERROR` (500)

**cURL**

```bash
curl -X POST "http://localhost:8765/workflow_record_answer/a1b2c3d4/q-001?answer=OAuth2+via+GitHub"
```

---

### GET /workflow_list_questions/{session_id}

List all questions with answer status.

**Response payload**

```json
{
  "questions": [
    {
      "id": "q-001",
      "text": "What is the primary purpose?",
      "answer": "A task management app",
      "answered_at": 1712345700.0,
      "answered": true
    }
  ]
}
```

**cURL**

```bash
curl http://localhost:8765/workflow_list_questions/a1b2c3d4
```

---

### POST /workflow_freeze_spec/{session_id}

Freeze the specification. Advances phase to `architecture` and records timestamp.

**Response payload**

```json
{ "signal": "spec_frozen" }
```

**Error codes**: `SPEC_FREEZE_ERROR` (500)

**cURL**

```bash
curl -X POST http://localhost:8765/workflow_freeze_spec/a1b2c3d4
```

---

### GET /workflow_get_spec/{session_id}

Get the frozen spec (all answered Q&A pairs).

**Response payload**

```json
{
  "session_id": "a1b2c3d4",
  "questions": [
    { "id": "q-001", "text": "...", "answer": "...", "answered": true }
  ],
  "frozen_at": 1712345800.0,
  "frozen": true
}
```

**Error codes**: `NOT_FOUND` (404 — no answered questions), `SPEC_GET_ERROR` (500)

**cURL**

```bash
curl http://localhost:8765/workflow_get_spec/a1b2c3d4
```

---

### POST /workflow_store_proposal/{session_id}

Store an architecture proposal.

**Query Parameters**

| Name      | Type    | Description                    |
|-----------|---------|--------------------------------|
| `paradigm`| string  | `oop`, `functional`, or `data` |
| `content` | string  | Markdown proposal text         |
| `score`   | float   | Evaluation score 0–100         |

**Response payload**

```json
{ "proposal_id": "p1a2b3c4", "paradigm": "oop" }
```

**cURL**

```bash
curl -X POST "http://localhost:8765/workflow_store_proposal/a1b2c3d4?paradigm=oop&content=...&score=92.5"
```

---

### GET /workflow_list_proposals/{session_id}

List architecture proposals.

**Response payload**

```json
{
  "proposals": [
    { "id": "p1", "paradigm": "oop", "content": "...", "score": 92.5, "created_at": 1712345900.0 }
  ]
}
```

**cURL**

```bash
curl http://localhost:8765/workflow_list_proposals/a1b2c3d4
```

---

### GET /workflow_next_task/{session_id}

Get the next pending task with a model recommendation.

**Response payload** (task available):

```json
{
  "id": "t1a2b3c4",
  "title": "Implement user authentication",
  "description": "JWT-based auth with refresh tokens",
  "acceptance_criteria": "Given a valid login, when the user submits...",
  "assigned_model": null,
  "recommended_model": "claude-3-5-sonnet",
  "complexity_score": 12.5
}
```

**Response payload** (all done):

```json
{ "signal": "all_tasks_complete" }
```

**cURL**

```bash
curl http://localhost:8765/workflow_next_task/a1b2c3d4
```

---

### POST /workflow_add_task/{session_id}

Add a task to a session.

**Query Parameters**

| Name                   | Type   | Description              |
|------------------------|--------|--------------------------|
| `title`                | string | Task title (required)    |
| `description`          | string | Detailed description     |
| `acceptance_criteria`  | string | Gherkin scenarios        |

**Response payload**

```json
{ "task_id": "t1a2b3c4", "session_id": "a1b2c3d4", "title": "Build REST API", "status": "pending" }
```

**cURL**

```bash
curl -X POST "http://localhost:8765/workflow_add_task/a1b2c3d4?title=Build+REST+API"
```

---

### POST /workflow_run_tests/{session_id}

Record test run results for a task.

**Query Parameters**

| Name           | Type   | Default | Description             |
|----------------|--------|---------|-------------------------|
| `task_id`      | string |         | Associated task ID      |
| `passed`       | int    | `0`     | Passing test count      |
| `failed`       | int    | `0`     | Failing test count      |
| `coverage_pct` | float  | `0.0`   | Coverage percentage     |
| `runner_output`| string | `""`    | Raw test output         |

**Response payload**

```json
{
  "run_id": "r1a2b3c4",
  "task_id": "t1a2b3c4",
  "ok": true,
  "passed": 15,
  "failed": 0,
  "coverage_pct": 87.5
}
```

**cURL**

```bash
curl -X POST "http://localhost:8765/workflow_run_tests/a1b2c3d4?task_id=t1a2b3c4&passed=15&coverage_pct=87.5"
```

---

### POST /workflow_complete_task/{session_id}/{task_id}

Mark a task as complete with optional test results.

**Path Parameters**: `session_id`, `task_id`

**Response payload**

```json
{ "task_id": "t1a2b3c4", "session_id": "a1b2c3d4", "status": "completed" }
```

**Error codes**: `COMPLETION_ERROR` (500), `TASK_COMPLETE_ERROR` (500)

**cURL**

```bash
curl -X POST http://localhost:8765/workflow_complete_task/a1b2c3d4/t1a2b3c4
```

---

### POST /workflow_start_agent/{session_id}

Start a background job for async agent execution.

**Query Parameters**

| Name         | Type   | Description                           |
|--------------|--------|---------------------------------------|
| `agent_name` | string | Agent name (e.g. `bisset-architect`)  |
| `task_id`    | string | Optional associated task              |

**Response payload**

```json
{ "job_id": "j1a2b3c4", "status": "created" }
```

**cURL**

```bash
curl -X POST "http://localhost:8765/workflow_start_agent/a1b2c3d4?agent_name=bisset-architect"
```

---

### GET /workflow_get_job_status/{session_id}/{job_id}

Get background job status and result.

**Response payload**

```json
{
  "id": "j1a2b3c4",
  "agent_name": "bisset-architect",
  "status": "completed",
  "result": { "proposals": 3, "selected": "oop" },
  "created_at": 1712345000.0,
  "updated_at": 1712345060.0
}
```

Status values: `created` | `running` | `completed` | `failed`

**Error codes**: `NOT_FOUND` (404)

**cURL**

```bash
curl http://localhost:8765/workflow_get_job_status/a1b2c3d4/j1a2b3c4
```

---

### GET /workflow_list_jobs/{session_id}

List background jobs for a session.

**Query Parameters**

| Name     | Type   | Description                  |
|----------|--------|------------------------------|
| `status` | string | Optional filter by status    |

**Response payload**

```json
{ "jobs": [ { "id": "j1a2b3c4", "agent_name": "bisset-architect", "status": "completed", ... } ] }
```

**cURL**

```bash
curl "http://localhost:8765/workflow_list_jobs/a1b2c3d4?status=running"
```

---

### GET /workflow_status/{session_id}

Get overall workflow status including background jobs.

**Response payload**

```json
{
  "session_id": "a1b2c3d4",
  "phase": "architecture",
  "sub_phase": null,
  "status": "active",
  "background_jobs": [
    { "id": "j1a2b3c4", "agent_name": "bisset-architect", "status": "running" }
  ]
}
```

**Error codes**: `NOT_FOUND` (404)

**cURL**

```bash
curl http://localhost:8765/workflow_status/a1b2c3d4
```

---

### GET /workflow_get_events/{session_id}

Get event log for a session.

**Query Parameters**

| Name    | Type | Default | Description                  |
|---------|------|---------|------------------------------|
| `limit` | int  | `100`   | Max events to return         |

**Response payload**

```json
{
  "events": [
    {
      "id": "e1a2b3c4",
      "event_type": "task_completed",
      "data": { "task_id": "t1a2b3c4" },
      "timestamp": 1712346000.0,
      "success": true,
      "duration_ms": null
    }
  ]
}
```

**cURL**

```bash
curl "http://localhost:8765/workflow_get_events/a1b2c3d4?limit=50"
```

---

### GET /prompts/phase/{phase_name}

Return the system prompt for a workflow phase.

**Path Parameters**

| Name         | Type   | Description                                                                     |
|--------------|--------|---------------------------------------------------------------------------------|
| `phase_name` | string | One of: `interview`, `validation`, `architecture`, `gherkin`, `implementation`, `coverage`, `done` |

**Response payload**

```json
{
  "phase": "interview",
  "prompt": "You are bisset-interview. Your task is to gather requirements..."
}
```

**Error codes**: `NOT_FOUND` (404 — unknown phase name)

**cURL**

```bash
curl http://localhost:8765/prompts/phase/interview
```
