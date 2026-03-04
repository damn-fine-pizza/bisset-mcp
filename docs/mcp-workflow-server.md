# MCP Workflow Server

A deterministic, role-based software-building workflow server using the **Model Context Protocol** (MCP) over **STDIO transport**.

The LLM lives in the host (Copilot CLI). This server provides **Prompts + Resources + Tools** and manages workflow state via a state machine backed by SQLite.

---

## Prerequisites

- Python 3.12+ via `pyenv` env `bisset-mcp`
- MCP SDK: `pip install "mcp[cli]"` (already in `bisset-mcp`)

---

## Running the server locally

```bash
# From repo root (pyenv will auto-select bisset-mcp via .python-version)
python -m orchestrator.mcp_workflow_server
```

The server speaks the MCP protocol over STDIO (line-delimited JSON-RPC). It is meant to be launched as a subprocess by a Copilot CLI MCP host.

---

## Registering in Copilot CLI

```bash
# Add as a local STDIO MCP server
/mcp add name=bisset-workflow \
         cmd="python -m orchestrator.mcp_workflow_server" \
         transport=stdio \
         cwd="$(pwd)"
```

---

## Example interactive session

### 1. Start workflow

```json
{"method": "tools/call", "params": {"name": "workflow_start", "arguments": {"project_meta": {"name": "MyApp"}}}}
```

### 2. Get next question

```json
{"method": "tools/call", "params": {"name": "workflow_next_question", "arguments": {}}}
```

### 3. Record answer

```json
{"method": "tools/call", "params": {"name": "workflow_record_answer", "arguments": {"question_id": "q-001", "answer_text": "MyApp"}}}
```

Repeat steps 2–3 until `next_question` returns `{"done": true}`.

### 4. Freeze spec

```json
{"method": "tools/call", "params": {"name": "workflow_freeze_spec", "arguments": {}}}
```

This generates:
- `resources/spec_current.md` — frozen project specification
- `resources/decisions/adr-0001.md` — initial ADR stub
- `resources/plan/workbreakdown.yaml` — task breakdown

### 5. Execute task loop

```json
{"method": "tools/call", "params": {"name": "workflow_next_task", "arguments": {}}}
```

```json
{"method": "tools/call", "params": {"name": "workflow_accept_task_result", "arguments": {
  "task_id": "t-001",
  "summary": "Created project skeleton",
  "artifacts_changed": ["pyproject.toml", ".github/workflows/ci.yml"],
  "tests_run": ["test_smoke"],
  "test_results": {"passed": 1, "failed": 0}
}}}
```

Repeat until `workflow_is_done` returns `{"done": true}`.

---

## Available Prompts

| Name | Parameters |
|------|-----------|
| `roles/architect` | project_name, constraints, current_phase |
| `roles/product_owner` | project_name, business_goals |
| `roles/tech_lead` | project_name, tech_stack |
| `roles/test_engineer` | project_name, testing_scope |
| `roles/build_engineer` | project_name, ci_constraints |
| `phases/requirements_interview` | — |
| `phases/design_review` | — |
| `phases/implementation_loop` | — |

## Available Resources

| URI | Description |
|-----|-------------|
| `spec://current` | Frozen project specification |
| `constraints://current` | Runtime/language/CI constraints JSON |
| `decisions://adr-index` | ADR index |
| `plan://workbreakdown` | Task breakdown YAML |

## Available Tools

| Tool | Description |
|------|-------------|
| `workflow_start` | Start workflow, seed question catalog |
| `workflow_get_state` | Current phase + counts |
| `workflow_next_question` | Next unanswered question |
| `workflow_record_answer` | Record answer by question_id |
| `workflow_freeze_spec` | Freeze spec, write ADR + plan, enter execution phase |
| `workflow_next_task` | Next pending task |
| `workflow_accept_task_result` | Mark task done with evidence |
| `workflow_report` | Progress summary |
| `workflow_is_done` | True when all tasks complete |

---

## Running tests

```bash
python -m unittest discover -s orchestrator/mcp_workflow_server/tests -v
```

---

## Permissions / Safety

- The server **does not call any external LLM APIs**.
- Writes only under `orchestrator/mcp_workflow_server/resources/` and `orchestrator/mcp_workflow_server/workflow.db`.
- Does not execute shell commands or read files outside the repo.
- Do not run as root.
