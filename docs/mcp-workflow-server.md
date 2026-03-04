# MCP Workflow Server

Two-process architecture for zero-downtime backend reloads:

```
Copilot CLI ──STDIO──▶ mcp_server (thin proxy) ──HTTP──▶ workflow_server (FastAPI)
```

- **mcp_server**: FastMCP STDIO proxy. Stays alive as long as Copilot CLI is connected.
- **workflow_server**: FastAPI backend with engine, storage, catalog, renderers. Can be restarted/hot-reloaded independently.

---

## Prerequisites

- pyenv env `bisset-mcp` (Python 3.12)
- `pip install -r orchestrator/workflow_server/requirements.txt`

---

## Running locally

### 1 — Start the backend

```bash
python -m orchestrator.workflow_server
# or with hot-reload:
uvicorn orchestrator.workflow_server.app:app --reload --port 8765
```

### 2 — Start the MCP proxy (in a separate terminal or as subprocess)

```bash
python -m orchestrator.mcp_server
```

The proxy reads `WORKFLOW_BACKEND_URL` (default `http://127.0.0.1:8765`).

---

## Registering in Copilot CLI

```bash
/mcp add name=bisset-workflow \
         cmd="python -m orchestrator.mcp_server" \
         transport=stdio \
         cwd="$(pwd)"
```

---

## Example session

### Start workflow

```json
{"name": "workflow_start", "arguments": {"project_meta": {"name": "MyApp"}}}
```

### Interview loop

```json
{"name": "workflow_next_question", "arguments": {}}
{"name": "workflow_record_answer", "arguments": {"question_id": "q-001", "answer_text": "MyApp"}}
```

Repeat until `next_question` returns `{"done": true}`.

### Freeze spec

```json
{"name": "workflow_freeze_spec", "arguments": {}}
```

Produces:
- `workflow_server/resources/spec_current.md`
- `workflow_server/resources/decisions/adr-0001.md`
- `workflow_server/resources/plan/workbreakdown.yaml`

### Execution loop

```json
{"name": "workflow_next_task", "arguments": {}}
{"name": "workflow_accept_task_result", "arguments": {
  "task_id": "t-001", "summary": "done",
  "artifacts_changed": [], "tests_run": [], "test_results": {}
}}
```

Repeat until `workflow_is_done` returns `{"done": true}`.

---

## Prompts

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

## Resources

| URI | Description |
|-----|-------------|
| `spec://current` | Frozen project specification |
| `constraints://current` | Runtime/language/CI constraints |
| `decisions://adr-index` | ADR index |
| `plan://workbreakdown` | Task breakdown YAML |

## Tools

| Tool | Description |
|------|-------------|
| `workflow_start` | Start workflow, seed questions |
| `workflow_get_state` | Current phase + counts |
| `workflow_next_question` | Next unanswered question |
| `workflow_record_answer` | Record answer |
| `workflow_freeze_spec` | Freeze spec, enter execution |
| `workflow_next_task` | Next pending task |
| `workflow_accept_task_result` | Mark task done |
| `workflow_report` | Progress summary |
| `workflow_is_done` | True when complete |

---

## Tests

```bash
# workflow_server (FastAPI + engine)
python -m unittest discover -s orchestrator/workflow_server/tests -v

# mcp_workflow_server legacy unit tests
python -m unittest discover -s orchestrator/mcp_workflow_server/tests -v
```

---

## Safety

- No external LLM API calls.
- Writes only under `orchestrator/workflow_server/resources/` and `workflow.db`.
- `mcp_server` only proxies; it writes nothing to disk.
- Do not run as root.
